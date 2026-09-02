"""The single seam where A2UI payloads enter the AG-UI event stream.

⚠️ UNRESOLVED AGAINST THE SPECIFICATIONS ⚠️

AG-UI advertises day-zero A2UI compatibility, and A2UI names AG-UI as a
transport - but A2UI v0.9.1 defines its message mapping against **A2A message
Parts**, and no canonical AG-UI envelope for an A2UI payload is documented in
either specification. Published examples improvise: one uses a `GenerativeUI`
event with `format: "a2ui"` alongside a `MessageDelta` event, and `MessageDelta`
is not an AG-UI event type at all.

Rather than invent an envelope and scatter the guess across the codebase, the
guess lives here, once. Pantheon emits A2UI as an AG-UI `Custom` event named
`a2ui`, carrying one A2UI message per event.

IF A CANONICAL ENVELOPE IS STANDARDISED
---------------------------------------
Exactly two things change, both in this file:

1. ``EVENT_NAME`` / the choice of `Custom` - the AG-UI event actually used.
2. ``to_wire()`` - the payload shape wrapped inside it.

Nothing else in Pantheon constructs an A2UI wire message. `core/ui/` builds
A2UISurface objects; `translator.py` decides *when* to emit; only this module
decides *how*. The cost of being wrong is bounded to one function and one
constant, and that is the entire reason this seam exists.

A SURFACE IS BUILT FROM A CONTRACT, NEVER FROM FREE TEXT
----------------------------------------------------------
The surfaces below are constructed here from `Action` and `AccessRequest`,
which are typed. No agent supplies component ids, labels or actions - it
supplies a request, and the shape of the prompt is Pantheon's.

That is what makes the component allowlist meaningful. An allowlist over
components an agent *chose* would be a filter on hostile input; an allowlist
over components only this module emits is a statement about what this module
does, which is checkable by reading it.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from ag_ui.core import CustomEvent, EventType

from core.contracts.action import Action
from core.contracts.credentials import AccessRequest
from core.contracts.ui import (
    A2UIAction,
    A2UIComponent,
    A2UIComponentType,
    A2UISurface,
    A2UISurfaceKind,
    UIActionResponse,
)

#: Name carried on the AG-UI `Custom` event. Change here if a canonical
#: envelope is standardised - and nowhere else.
EVENT_NAME = "a2ui"

#: A2UI server-to-client message types Pantheon emits. `deleteSurface` is
#: included for completeness; `updateDataModel` is emitted when a surface's
#: bound values change without its structure changing.
MESSAGE_TYPES = (
    "createSurface",
    "updateComponents",
    "updateDataModel",
    "deleteSurface",
)

#: The action names a returning client message may carry.
#:
#: Closed, because these are the two decisions that reach a backend that
#: changes something - `core/guardrails/approval_gate.py` and
#: `core/cerberus/broker.py`. An open set would mean a client could name an
#: action nothing routes, and the failure would be silence.
CLIENT_ACTIONS = ("approve", "reject", "grant", "deny")


class UnknownClientAction(ValueError):
    """A returning message naming an action Pantheon does not route."""


def to_wire(surface: A2UISurface, *, message_type: str = "createSurface") -> dict[str, Any]:
    """One A2UI message, as the payload of an AG-UI `Custom` event.

    THE GUESS LIVES HERE. If a canonical envelope is standardised, this function
    and `EVENT_NAME` are the two things that change.
    """
    if message_type not in MESSAGE_TYPES:
        raise ValueError(
            f"{message_type!r} is not an A2UI server-to-client message type "
            f"{list(MESSAGE_TYPES)}. Inventing one would put a message on the wire "
            "that no renderer has a branch for, and it would be dropped in silence."
        )
    return {
        "type": message_type,
        "surfaceId": str(surface.id),
        "catalogId": surface.catalog_id,
        "surface": surface.model_dump(mode="json"),
    }


def surface_event(surface: A2UISurface, *, message_type: str = "createSurface") -> CustomEvent:
    """The AG-UI event carrying one A2UI surface."""
    return CustomEvent(
        type=EventType.CUSTOM,
        name=EVENT_NAME,
        value=to_wire(surface, message_type=message_type),
    )


def from_wire(message: dict[str, Any]) -> UIActionResponse:
    """A returning client action message, as the contract the backend takes.

    Validated rather than trusted. This is the one inbound path from a renderer,
    so a message naming an action nothing routes is refused here - where the
    refusal is legible - instead of reaching a dispatcher that has no branch for
    it and returns quietly.

    The surface id is NOT taken on faith as authorisation. It identifies which
    prompt is being answered; whether the answer may be acted on is the approval
    gate's question, and it re-validates against the Action as it stands.
    """
    action = str(message.get("actionName") or message.get("action_name") or "")
    if action not in CLIENT_ACTIONS:
        raise UnknownClientAction(
            f"{action!r} is not one of {list(CLIENT_ACTIONS)}. A client action nothing "
            "routes would be accepted and then do nothing, which reads to whoever "
            "clicked it as the system having agreed."
        )

    surface_id = message.get("surfaceId") or message.get("surface_id")
    try:
        identifier = UUID(str(surface_id))
    except (ValueError, AttributeError, TypeError) as malformed:
        raise UnknownClientAction(
            f"the message names no usable surface: {surface_id!r}"
        ) from malformed

    return UIActionResponse(
        surface_id=identifier,
        source_component_id=str(
            message.get("sourceComponentId") or message.get("source_component_id") or ""
        ),
        action_name=action,
        context=dict(message.get("context") or {}),
    )


def approval_surface(action: Action) -> A2UISurface:
    """The prompt an operator answers to approve or reject one Action.

    Everything an approver needs to decide is on the card: what it does, to
    what, how wide the blast radius is, and how to undo it. An approval prompt
    that says only "approve action 7f3a?" is a prompt people learn to click
    through, and the whole gate then measures nothing.
    """
    surface_id = uuid4()
    return A2UISurface(
        id=surface_id,
        kind=A2UISurfaceKind.APPROVAL,
        root="card",
        investigation_id=None,
        agent_display_name=action.proposed_by,
        components=[
            A2UIComponent(
                id="card",
                component=A2UIComponentType.CARD,
                children=["what", "target", "radius", "rollback", "reason", "buttons"],
            ),
            _text("what", f"{action.operation} — approval required"),
            _text("target", f"Target: {action.target.kind}/{action.target.name}"),
            _text("radius", f"Blast radius: {action.blast_radius.value}"),
            _text("rollback", f"Rollback: {action.rollback or 'none stated'}"),
            _text("reason", f"Why: {action.reason}"),
            A2UIComponent(
                id="buttons",
                component=A2UIComponentType.ROW,
                children=["approve", "reject"],
            ),
            _button("approve", "Approve", "approve", {"action_id": str(action.id)}),
            _button("reject", "Reject", "reject", {"action_id": str(action.id)}),
        ],
    )


def access_surface(request: AccessRequest) -> A2UISurface:
    """The prompt a person answers to grant or deny one credential request.

    `request.reason` is on the card and is the point of it. Approving "an agent
    wants database access" is not a decision; approving a stated hypothesis is,
    which is why `AccessRequest.reason` is a required field rather than a note.
    """
    return A2UISurface(
        id=uuid4(),
        kind=A2UISurfaceKind.ACCESS_REQUEST,
        root="card",
        investigation_id=request.investigation_id,
        agent_display_name=request.agent,
        components=[
            A2UIComponent(
                id="card",
                component=A2UIComponentType.CARD,
                children=["what", "who", "why", "ttl", "buttons"],
            ),
            _text("what", f"{request.agent} requests {request.action.value} access"),
            _text("who", f"Credential: {request.credential_ref.name}"),
            _text("why", f"To test: {request.reason}"),
            _text("ttl", f"For up to {request.requested_ttl_seconds}s"),
            A2UIComponent(
                id="buttons", component=A2UIComponentType.ROW, children=["grant", "deny"]
            ),
            _button("grant", "Grant", "grant", {"request_id": str(request.id)}),
            _button("deny", "Deny", "deny", {"request_id": str(request.id)}),
        ],
    )


def renewal_surface(*, lease_id: str, agent: str) -> A2UISurface:
    """The prompt raised when a lease expired mid-run.

    Only for an EXPIRED lease. A revoked one is a decision somebody just made,
    and re-prompting for it would put the revocation back in front of the person
    who performed it as a question - `translator.py` is what makes that
    distinction, from `LeaseExpiredEvent.reason`.
    """
    return A2UISurface(
        id=uuid4(),
        kind=A2UISurfaceKind.ACCESS_REQUEST,
        root="card",
        agent_display_name=agent,
        components=[
            A2UIComponent(
                id="card", component=A2UIComponentType.CARD, children=["what", "buttons"]
            ),
            _text("what", f"{agent}'s lease {lease_id} expired mid-run. Grant it again?"),
            A2UIComponent(
                id="buttons", component=A2UIComponentType.ROW, children=["grant", "deny"]
            ),
            _button("grant", "Grant again", "grant", {"lease_id": lease_id}),
            _button("deny", "Leave it expired", "deny", {"lease_id": lease_id}),
        ],
    )


def _text(component_id: str, text: str) -> A2UIComponent:
    return A2UIComponent(id=component_id, component=A2UIComponentType.TEXT, text=text)


def _button(component_id: str, label: str, action: str, context: dict[str, str]) -> A2UIComponent:
    return A2UIComponent(
        id=component_id,
        component=A2UIComponentType.BUTTON,
        label=label,
        action=A2UIAction(event_name=action, context=dict(context)),
    )
