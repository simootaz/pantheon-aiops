"""Turns an inbound trigger into an Investigation, and runs it.

Zeus's entrypoint. The pieces beside it - classifier, planner, dispatcher,
aggregator - each do one thing and are separately testable; this is the order
they go in, and the place the lifecycle events are emitted from.

EVERY STATE CHANGE IS SAVED, NOT JUST THE LAST ONE
---------------------------------------------------
The Investigation is written at PENDING, at RUNNING, and at its terminal state.
A run that dies mid-dispatch therefore leaves a RUNNING row rather than nothing,
and the difference between "crashed" and "never arrived" stays visible - which
is the same reason `AgentOutcome` carries a status beside its findings.

The events are emitted in step with those saves. `InvestigationStartedEvent`
after the run is durable, not before: an event announcing a run that no reader
can then fetch is worse than a late event.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from core.bus import EventBus
from core.contracts.action import Action
from core.contracts.events import (
    ApprovalRequestedEvent,
    InvestigationCompletedEvent,
    InvestigationStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    VerdictReadyEvent,
)
from core.contracts.investigation import (
    DEFAULT_TENANT,
    Investigation,
    InvestigationState,
    Trigger,
)
from core.contracts.plan import StepStatus
from core.guardrails.approval_gate import ApprovalGate
from core.guardrails.proposal import Proposal, propose_all
from core.orchestrator import aggregator, dispatcher, planner
from core.orchestrator.classifier import classify, scenario_of
from core.orchestrator.correlation import correlate
from core.store.investigations import InvestigationStore

#: How far back an agent looks when the trigger does not say.
#:
#: Alertmanager tells us an alert is firing, not when the underlying fault
#: began. Five minutes is the window the detection thresholds were measured
#: over at 630x compression; a longer one would dilute the crossing fraction
#: that `Finding.confidence` reports, and a shorter one can miss the sustain
#: requirement entirely.
DEFAULT_LOOKBACK = timedelta(minutes=5)


async def investigate(
    trigger: Trigger,
    *,
    store: InvestigationStore,
    bus: EventBus,
    investigation_id: UUID | None = None,
    lookback: timedelta = DEFAULT_LOOKBACK,
    gate: ApprovalGate | None = None,
    tenant: str = DEFAULT_TENANT,
) -> Investigation:
    """Classify, plan, dispatch, aggregate, propose. Returns the Investigation.

    `gate` is where a remediation that needs a person goes. Optional because a
    run that recommends nothing needs none - which is every run today - and
    required the moment a verdict recommends something: see
    `_propose_remediations` for why that case raises rather than skipping.
    """
    now = datetime.now(UTC)
    classification = classify(trigger)

    investigation = Investigation(
        id=investigation_id or uuid4(),
        state=InvestigationState.PENDING,
        trigger=trigger,
        created_at=now,
        scenario=scenario_of(trigger),
        # From the receiver that established it - a scheduled run's principal -
        # and the default for receivers that have none. Alertmanager and GitHub
        # carry no identity, so their runs land in the default tenant.
        tenant=tenant,
    )
    await store.save(investigation)

    try:
        plan = planner.build(classification)
    except planner.NoAgentForDomain as unroutable:
        investigation = investigation.model_copy(
            update={
                "state": InvestigationState.FAILED,
                "completed_at": datetime.now(UTC),
            }
        )
        await store.save(investigation)
        await bus.publish(
            InvestigationCompletedEvent(
                investigation_id=investigation.id,
                state=InvestigationState.FAILED.value,
                partial=True,
            ),
            investigation_id=investigation.id,
        )
        raise unroutable

    investigation = investigation.model_copy(
        update={
            "state": InvestigationState.RUNNING,
            "started_at": datetime.now(UTC),
            "plan": plan,
        }
    )
    await store.save(investigation)
    await bus.publish(
        InvestigationStartedEvent(investigation_id=investigation.id),
        investigation_id=investigation.id,
    )

    window_end = datetime.now(UTC)
    window_start = window_end - lookback

    completed_steps = []
    findings = []
    resolutions = []
    accounting = []
    for step in plan:
        await bus.publish(
            StepStartedEvent(investigation_id=investigation.id, agent=step.agent),
            investigation_id=investigation.id,
        )
        finished, outcome = await dispatcher.run_step(
            step,
            investigation_id=investigation.id,
            trigger=trigger,
            window_start=window_start,
            window_end=window_end,
        )
        completed_steps.append(finished)
        findings.extend(outcome.findings)
        # Every model consultation the step made, whether or not it completed.
        # `Investigation.resolutions` is what answers "what did this run cost",
        # and the runs anybody asks that about are the ones that went wrong.
        resolutions.extend(outcome.resolutions)
        # Appended for every dispatched step, including the degraded ones -
        # see AgentOutcome.accounting.
        if outcome.accounting is not None:
            accounting.append(outcome.accounting)
        await bus.publish(
            StepFinishedEvent(
                investigation_id=investigation.id,
                agent=step.agent,
                finding_count=len(outcome.findings),
            ),
            investigation_id=investigation.id,
        )

    # After every step, before the verdict. Correlation reads what ALL the
    # agents produced, so it cannot run per-step - and the verdict should carry
    # the groups rather than leaving a reader to assemble them.
    findings.extend(correlate(findings))

    verdict = aggregator.aggregate(
        investigation.id, findings, completed_steps, explains=classification.explains
    )
    partial = any(s.status is not StepStatus.COMPLETE for s in completed_steps)

    # Every remediation the verdict recommends goes through the policy, and the
    # ones that need a person open a request. Before this, `open_request` had no
    # production caller at all: `executor.execute` refused an Action needing
    # approval and nothing turned that refusal into somebody being asked.
    proposals = _propose_remediations(verdict.recommended_actions, gate=gate)
    waiting = [p for p in proposals if p.waiting]

    # AWAITING_APPROVAL, not COMPLETED. The state existed in the contract and
    # nothing ever set it, so a run that had asked a person and a run that was
    # finished were the same row - and the second is the one an operator stops
    # reading.
    state = InvestigationState.AWAITING_APPROVAL if waiting else InvestigationState.COMPLETED

    investigation = investigation.model_copy(
        update={
            "state": state,
            # Set only when the run is actually over. A completion time on a run
            # still waiting for an approver would make every duration measured
            # from it wrong, and would read as finished to anything sorting by
            # it.
            "completed_at": datetime.now(UTC) if not waiting else None,
            "plan": completed_steps,
            "findings": findings,
            "resolutions": resolutions,
            "accounting": accounting,
            "verdict": verdict,
        }
    )
    await store.save(investigation)

    await bus.publish(
        VerdictReadyEvent(investigation_id=investigation.id, verdict=verdict),
        investigation_id=investigation.id,
    )

    # After the verdict, because the approval card is read in the context of the
    # conclusion that produced it. `api/agui/translator.py` turns each of these
    # into the A2UI approval surface - which it has been able to do since the
    # surface landed, with nothing publishing the event.
    for pending in waiting:
        await bus.publish(
            ApprovalRequestedEvent(investigation_id=investigation.id, action=pending.action),
            investigation_id=investigation.id,
        )

    if not waiting:
        # `InvestigationCompletedEvent` says a run reached a terminal state, and
        # AWAITING_APPROVAL is not one. Emitting it anyway would close the AG-UI
        # stream on the reader who is being asked to answer.
        await bus.publish(
            InvestigationCompletedEvent(
                investigation_id=investigation.id,
                state=state.value,
                partial=partial,
            ),
            investigation_id=investigation.id,
        )
    return investigation


def _propose_remediations(
    actions: list[Action],
    *,
    gate: ApprovalGate | None,
) -> list[Proposal]:
    """Put each recommended Action through the policy, opening requests as needed.

    A run with no gate and nothing to propose is ordinary - the simulator, and
    every run today, since the aggregator recommends nothing yet. A run with no
    gate and something to propose is a misconfiguration, and it raises: dropping
    the proposals would mean a remediation that needed a person was never put in
    front of one, and the run would report itself complete.
    """
    if not actions:
        return []
    if gate is None:
        raise RuntimeError(
            f"the verdict recommends {len(actions)} action(s) and no approval gate was "
            "supplied, so nothing can be put in front of a person. Pass `gate=` - "
            "silently dropping them would report the run as complete."
        )
    return propose_all(actions, gate=gate)


async def get(investigation_id: UUID, *, store: InvestigationStore) -> Investigation | None:
    """Read one back. Absence is an answer, not an error."""
    return await store.get(investigation_id)
