"""The only path from a proposed Action to a system that changes.

Until now `policy.py` and `approval_gate.py` guarded a path that did not exist:
no connector had a write tool, so the guardrails were correct and unreachable.
`alertmanager.create_silence` is the first one, and this is what stands between
it and an agent.

WHY AGENTS DO NOT EXECUTE
---------------------------
An agent proposes an `Action`. It never runs one, and it cannot: no agent
manifest declares a mutating tool, and `tests/unit/test_write_path.py` fails the
build if one does. That is the read/write split the connector layer has carried
since Phase 1 - *an agent that cannot reach a write tool is safe by
construction; an agent trusted not to call one is safe by convention.*

So this module does not go through `BoundTools`. An agent's toolset is its
allowlist, and adding a write to it would be handing the agent the capability
this file exists to withhold.

THE THREE CHECKS, AND WHY NONE IS REDUNDANT
---------------------------------------------
1. **Policy** decides whether the Action may run at all. A DENY stops here, and
   no approval can move it - that is what `too-wide-for-production` means.
2. **Approval** is required when policy asks for one, and is re-validated
   against the Action *as it is now*. An approval is for the content the
   approver read, not for an id.
3. **The receipt** is written whatever happens, including the refusals.

Skipping the third is the tempting one, and it is the one that matters most
afterwards: an Action that was refused and an Action nobody tried look identical
without it, and only the second is a bug.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from core.config import Environment
from core.contracts.action import Action, ActionReceipt, ExecutionState
from core.guardrails.approval_gate import ApprovalRequest, may_execute
from core.guardrails.policy import Decision, evaluate

#: What actually performs the operation. A callable rather than a connector
#: object, so the executor depends on the shape of a call and not on which
#: connector is behind it - and a test can hand over one that records.
Performer = Callable[[str, dict[str, Any]], Awaitable[Any]]


class NotPermitted(RuntimeError):
    """The Action was refused before anything ran.

    Carries the receipt, so a caller that catches this still has the record.
    An exception that discarded it would leave the refusal in a log line and
    nowhere in the Investigation.
    """

    def __init__(self, reason: str, receipt: ActionReceipt) -> None:
        super().__init__(reason)
        self.receipt = receipt


def _receipt(state: ExecutionState, detail: str, connector: str) -> ActionReceipt:
    return ActionReceipt(at=datetime.now(tz=UTC), state=state, connector=connector, detail=detail)


async def execute(
    action: Action,
    *,
    perform: Performer,
    connector: str,
    approval: ApprovalRequest | None = None,
    environment: Environment | None = None,
) -> ActionReceipt:
    """Run the Action, or refuse it and say which check said no.

    Returns the receipt on success. Raises `NotPermitted` - carrying a receipt -
    on every refusal, so a caller cannot mistake a refusal for a completed
    action by forgetting to inspect a returned state.
    """
    ruling = evaluate(action, environment=environment)

    if ruling.decision is Decision.DENY:
        receipt = _receipt(
            ExecutionState.SKIPPED,
            f"denied by policy ({ruling.rule}): {ruling.because}",
            connector,
        )
        raise NotPermitted(f"policy denied {action.id}: {ruling.rule}", receipt)

    if ruling.decision is Decision.REQUIRE_APPROVAL:
        if approval is None:
            receipt = _receipt(
                ExecutionState.SKIPPED,
                f"needs approval ({ruling.rule}) and none was supplied",
                connector,
            )
            raise NotPermitted(f"{action.id} needs an approval and none was given", receipt)

        # Re-validated here rather than trusted from whoever passed it. The
        # approval is checked against the Action AS IT IS NOW - approved as a
        # dry run and executed after `dry_run` was cleared is the same id and a
        # different act.
        if not may_execute(approval, action):
            receipt = _receipt(
                ExecutionState.SKIPPED,
                "the approval does not cover this action as it stands: it has "
                "expired, was rejected, or the action changed since it was read",
                connector,
            )
            raise NotPermitted(f"{action.id} has no live approval", receipt)

    try:
        detail = await perform(action.operation, dict(action.parameters))
    except Exception as failure:
        # A receipt for the failure too. "It ran and broke" and "it never ran"
        # are different facts and both need to survive.
        receipt = _receipt(ExecutionState.FAILED, f"{type(failure).__name__}: {failure}", connector)
        raise NotPermitted(f"{action.id} failed: {failure}", receipt) from failure

    return _receipt(
        # DRY_RUN rather than SUCCEEDED when nothing changed. The contract
        # refuses a SUCCEEDED action that still claims dry_run, and reporting a
        # rehearsal as a success is how a plan looks applied when it is not.
        ExecutionState.DRY_RUN if action.dry_run else ExecutionState.SUCCEEDED,
        str(detail)[:500],
        connector,
    )
