"""The Approval Gate as an A2UI surface.

The clearest fit for generative UI in Pantheon: the agent describes the approval
it needs, the host renders it from the allowlist, and the answer returns over
AG-UI to the existing core.guardrails.approval_gate.

There is no second inbox and no second decision path - the surface is a
rendering of the same request the Approval Gate already understands.

THE CARD CARRIES WHAT AN APPROVER NEEDS TO DECIDE
---------------------------------------------------
Target, blast radius, rollback, and the reason the Action was proposed. Not an
id. "Approve action 7f3a?" is a prompt people learn to click through, and a gate
answered by reflex measures nothing - which is worse than no gate, because the
audit trail then records a decision nobody made.

`rollback` is on the card because `core/contracts/action.py` refuses to build a
wide Action without one: the moment somebody is deciding is the worst moment to
be working out whether it can be reversed.

THE SURFACE GRANTS NOTHING
----------------------------
It is a rendering. The returning action reaches the gate, which re-validates it
against the Action *as it is now* - `may_execute` checks the approval digest
against current content, so approving a dry run and then clearing `dry_run` is
refused. A surface that could authorise by itself would bypass that.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from uuid import UUID, uuid4

from core.contracts.action import Action
from core.contracts.ui import A2UISurface, A2UISurfaceKind
from core.ui import components

#: The two answers an approval prompt accepts. Closed, and matched by
#: `api/agui/a2ui_channel.CLIENT_ACTIONS` - a button naming an action the
#: inbound path does not route is a button that does nothing when pressed.
APPROVE = "approve"
REJECT = "reject"


def approval_surface(action: Action, *, investigation_id: UUID | None = None) -> A2UISurface:
    """The prompt an operator answers to approve or reject one Action."""
    return A2UISurface(
        id=uuid4(),
        kind=A2UISurfaceKind.APPROVAL,
        root="card",
        investigation_id=investigation_id,
        # The proposer, not the approver. `agent_display_name` says who is
        # ASKING - and the gate separately refuses a proposer approving their
        # own request, which is the check this label makes legible.
        agent_display_name=action.proposed_by,
        components=[
            components.card("card", "what", "target", "radius", "rollback", "reason", "buttons"),
            components.text("what", f"{action.operation} — approval required"),
            components.text("target", f"Target: {action.target.kind}/{action.target.name}"),
            components.text("radius", f"Blast radius: {action.blast_radius.value}"),
            components.text("rollback", f"Rollback: {action.rollback or 'none stated'}"),
            components.text("reason", f"Why: {action.reason}"),
            components.row("buttons", "approve", "reject"),
            components.button(
                "approve", "Approve", action=APPROVE, context={"action_id": str(action.id)}
            ),
            components.button(
                "reject", "Reject", action=REJECT, context={"action_id": str(action.id)}
            ),
        ],
    )
