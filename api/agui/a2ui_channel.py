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

WHAT THIS MODULE DOES NOT DO
------------------------------
It does not BUILD surfaces. `core/ui/` does - `approval_surface`,
`access_surface` and `renewal_surface` live there, on the component builders.

They were briefly here, which contradicted the paragraph above in the same file:
"core/ui/ builds A2UISurface objects; translator.py decides when to emit; only
this module decides how." Two places constructing an approval card is two places
that can disagree about what an approver is shown, and the one that drifts is
whichever is not the one being read.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ag_ui.core import CustomEvent, EventType

from core.contracts.ui import A2UISurface, UIActionResponse

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
