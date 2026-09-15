"""Turning a proposed Action into a decision, and - when it needs one - a person.

THE LINK THAT WAS MISSING
---------------------------
The gate has held approvals since `approval_gate.py` landed, and `open_request`
had no production caller. `executor.execute` refused an Action needing approval
with "needs approval and none was supplied" - correctly, and into a void: no
code path turned that refusal into somebody being asked, so the queue was a
queue nothing could reach.

This is the request half. `executor.execute` is the spend half; it takes an
approval and re-validates it. Proposing and spending are separate functions
because they happen at different moments, minutes or hours apart, and a single
call that did both would have to block on a human.

WHY THIS DOES NOT LIVE IN `execute`
-------------------------------------
`execute` runs an Action. An Action that needs approval is not going to run now
by definition, so an `execute` that opened a request would have two return
shapes meaning "ran" and "asked" - and every caller would have to tell them
apart before knowing whether anything happened. Worse, a retry would open a
second request for the same Action, and the gate has no way to know the first
one is the same act.

WHY A DENY DOES NOT OPEN A REQUEST
------------------------------------
The gate refuses one, and this refuses to try. Opening a request for a denied
Action manufactures a way past the deny: somebody approves it, the receipt
records an approval, and the only thing standing between that and execution is
`executor.execute` re-evaluating the policy. Which it does - but a system whose
audit trail contains an approval for an Action policy denied is a system that
has already told a confusing story.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Environment
from core.contracts.action import Action
from core.guardrails.approval_gate import ApprovalGate, ApprovalRequest
from core.guardrails.policy import Decision, Ruling, evaluate


@dataclass(frozen=True)
class Proposal:
    """What the policy said, and who was asked.

    `approval` is set only for REQUIRE_APPROVAL. A caller reading it as "is
    somebody deciding" is right; one reading its absence as permission is not,
    which is why `ready` and `refused` are named rather than left to callers
    comparing `approval is None`.
    """

    action: Action
    ruling: Ruling
    #: The request opened for a person, or `None`.
    approval: ApprovalRequest | None = None

    @property
    def ready(self) -> bool:
        """True only when nothing further is needed before executing.

        Named rather than inferred. `approval is None` is true for an ALLOW and
        also for a DENY, and a caller that treated the absence of a request as
        clearance would execute exactly the Actions policy refused.
        """
        return self.ruling.decision is Decision.ALLOW

    @property
    def refused(self) -> bool:
        """True when no approval can help. A DENY is not a slow yes."""
        return self.ruling.decision is Decision.DENY

    @property
    def waiting(self) -> bool:
        """True when a person has been asked and has not answered."""
        return self.approval is not None


def propose(
    action: Action,
    *,
    gate: ApprovalGate,
    environment: Environment | None = None,
) -> Proposal:
    """Evaluate one Action and open an approval request if it needs one.

    Returns rather than raises, in all three cases. A DENY is an ordinary
    outcome of proposing something - the policy exists to produce it - and a
    caller proposing several Actions should get several answers rather than
    stopping at the first refusal.

    `environment` is passed through to `evaluate` for the reason it is
    injectable there: a test can ask what production would say without being
    production.
    """
    ruling = evaluate(action, environment=environment)

    if ruling.decision is not Decision.REQUIRE_APPROVAL:
        return Proposal(action=action, ruling=ruling)

    # The one call. `open_request` refuses an ALLOW or a DENY itself, so the
    # branch above is not the only thing keeping a denied Action out of the
    # queue - but reaching that refusal would mean this function had already
    # decided to ask about something nobody may approve.
    return Proposal(action=action, ruling=ruling, approval=gate.open_request(action, ruling))


def propose_all(
    actions: list[Action],
    *,
    gate: ApprovalGate,
    environment: Environment | None = None,
) -> list[Proposal]:
    """Propose several, in order, and answer for every one.

    One refusal does not stop the rest. A verdict recommending three
    remediations, one of which policy denies, should put the other two in front
    of a person rather than producing nothing - and a caller that wants
    all-or-nothing can read the list and decide that for itself, which is a
    decision it can make and this function cannot.
    """
    return [propose(action, gate=gate, environment=environment) for action in actions]


__all__ = ["Proposal", "propose", "propose_all"]
