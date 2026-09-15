"""Attaching audit entries to the Investigation they belong to.

Safe to expose, because every credential in an `AuditEntry` is a
`CredentialRef` - an identifier, never a value. That is the property that lets
the trail travel with the Investigation an agent and a dashboard can both read.

WHY THE WRITE PATH WRITES HERE
--------------------------------
`Investigation.audit` has existed since Phase 1 with no writer, so an
investigation that silenced an alert recorded the receipt and nothing about the
decision behind it. `core/guardrails/executor.py` now produces exactly that:
a policy ruling, an approval or the absence of one, and an outcome.

Those are not credential events, and `AuditEvent` is a credential vocabulary -
so they map onto the members that already mean what happened rather than
growing the enum to fit. A refusal is `DENIED`, an approval sought is
`APPROVAL_REQUESTED`, and an executed action is `GRANTED`: the thing was
permitted and went ahead.

Stretching an enum is a real cost and it is taken deliberately here. The
alternative - a second audit vocabulary for actions - means two trails to read
and two to keep in step, and the question anybody asks is "what did this run do
and who let it", not "which subsystem recorded it".

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from uuid import UUID

from core.cerberus.audit.log import AuditLog
from core.contracts.action import Action, ActionReceipt, ExecutionState
from core.contracts.credentials import AuditEntry, AuditEvent
from core.contracts.investigation import Investigation

#: Execution states that mean the Action ran, whatever came of it. SKIPPED is
#: absent on purpose: it is what the executor writes when a check refused, and a
#: refusal is a DENIED entry rather than a run that went badly.
_RAN = frozenset(
    {
        ExecutionState.SUCCEEDED,
        ExecutionState.DRY_RUN,
        ExecutionState.FAILED,
        ExecutionState.ROLLED_BACK,
    }
)


def record_action(
    log: AuditLog,
    action: Action,
    receipt: ActionReceipt,
    *,
    investigation_id: UUID | None = None,
    actor: str = "zeus",
) -> AuditEntry:
    """Record what happened to one Action, refusals included.

    A refusal is the entry that matters most afterwards. "Nobody proposed this"
    and "somebody proposed it and policy said no" are different facts about a
    system, and only the trail can tell them apart.
    """
    ran = receipt.state in _RAN
    return log.append(
        AuditEvent.GRANTED if ran else AuditEvent.DENIED,
        actor=actor,
        investigation_id=investigation_id,
        lease_id=receipt.lease_id,
        detail=(
            f"{action.operation} on {action.target.kind}/{action.target.name} "
            f"({action.blast_radius.value}) -> {receipt.state.value}: {receipt.detail}"
        ),
    )


def record_approval_sought(
    log: AuditLog,
    action: Action,
    *,
    investigation_id: UUID | None = None,
    actor: str = "zeus",
) -> AuditEntry:
    """Record that a human was asked, before the answer is known.

    Written when the request opens rather than when it is answered. An approval
    that expires unanswered leaves no other trace, and "nobody was asked" and
    "somebody was asked and did not reply" are the two states an operator most
    needs to tell apart at three in the morning.
    """
    return log.append(
        AuditEvent.APPROVAL_REQUESTED,
        actor=actor,
        investigation_id=investigation_id,
        detail=(
            f"{action.operation} on {action.target.kind}/{action.target.name} "
            f"({action.blast_radius.value}) is waiting for an approver"
        ),
    )


def attach(investigation: Investigation, log: AuditLog) -> Investigation:
    """Return the Investigation carrying this run's audit entries.

    A copy, because `Investigation` is a contract model and the store saves
    whole documents - mutating one in place would leave the saved copy and the
    in-memory one disagreeing about a trail that exists to be trusted.

    Only this run's entries. A log shared across runs would otherwise put one
    investigation's decisions on another's record.
    """
    entries = log.entries(investigation_id=investigation.id)
    return investigation.model_copy(update={"audit": [*investigation.audit, *entries]})
