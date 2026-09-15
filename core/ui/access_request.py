"""Cerberus AccessRequest as an A2UI surface.

Renders the agent's stated reason, the exact scope, the lease TTL and the
investigation id - because approving "an agent wants database access" is not a
decision, and approving a stated hypothesis is.

The returning action reaches Cerberus, which re-validates it against the request
it claims to answer. A surface cannot grant anything by itself.

THE REASON IS THE POINT OF THE CARD
-------------------------------------
`AccessRequest.reason` is a required contract field rather than a note, and this
is where that pays off. An approver reading "connection saturation may explain
the p99 latency" is making a decision about a hypothesis; an approver reading
"argus requests read access" is being asked to rubber-stamp.

WHAT IS DELIBERATELY NOT RENDERED
-----------------------------------
The credential itself, obviously - a surface carries a `CredentialRef`, which
identifies without disclosing. But also: no free text from the agent beyond
`reason`, which the contract already constrains to one field. A surface built
from arbitrary agent output could put a convincing sentence next to a Grant
button, and the component allowlist would not stop it because Text is allowed.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from uuid import uuid4

from core.contracts.credentials import AccessRequest
from core.contracts.ui import A2UISurface, A2UISurfaceKind
from core.ui import components

#: The two answers an access prompt accepts. Matched by
#: `api/agui/a2ui_channel.CLIENT_ACTIONS`.
GRANT = "grant"
DENY = "deny"


def access_surface(request: AccessRequest) -> A2UISurface:
    """The prompt a person answers to grant or deny one credential request."""
    return A2UISurface(
        id=uuid4(),
        kind=A2UISurfaceKind.ACCESS_REQUEST,
        root="card",
        investigation_id=request.investigation_id,
        agent_display_name=request.agent,
        components=[
            components.card("card", "what", "who", "why", "ttl", "buttons"),
            components.text("what", f"{request.agent} requests {request.action.value} access"),
            components.text("who", f"Credential: {request.credential_ref.name}"),
            components.text("why", f"To test: {request.reason}"),
            components.text("ttl", f"For up to {request.requested_ttl_seconds}s"),
            components.row("buttons", "grant", "deny"),
            components.button(
                "grant", "Grant", action=GRANT, context={"request_id": str(request.id)}
            ),
            components.button("deny", "Deny", action=DENY, context={"request_id": str(request.id)}),
        ],
    )


def renewal_surface(*, lease_id: str, agent: str) -> A2UISurface:
    """The prompt raised when a lease EXPIRED mid-run.

    Only for an expired lease. A revoked one is a decision somebody just made,
    and re-prompting would put the revocation back in front of the person who
    performed it as a question - `api/agui/translator.py` is what makes that
    distinction, from `LeaseExpiredEvent.reason`.
    """
    return A2UISurface(
        id=uuid4(),
        kind=A2UISurfaceKind.ACCESS_REQUEST,
        root="card",
        agent_display_name=agent,
        components=[
            components.card("card", "what", "buttons"),
            components.text("what", f"{agent}'s lease {lease_id} expired mid-run. Grant it again?"),
            components.row("buttons", "grant", "deny"),
            components.button("grant", "Grant again", action=GRANT, context={"lease_id": lease_id}),
            components.button(
                "deny", "Leave it expired", action=DENY, context={"lease_id": lease_id}
            ),
        ],
    )
