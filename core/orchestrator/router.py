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
from core.contracts.events import (
    InvestigationCompletedEvent,
    InvestigationStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    VerdictReadyEvent,
)
from core.contracts.investigation import Investigation, InvestigationState, Trigger
from core.contracts.plan import StepStatus
from core.orchestrator import aggregator, dispatcher, planner
from core.orchestrator.classifier import classify, scenario_of
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
) -> Investigation:
    """Classify, plan, dispatch, aggregate. Returns the finished Investigation."""
    now = datetime.now(UTC)
    classification = classify(trigger)

    investigation = Investigation(
        id=investigation_id or uuid4(),
        state=InvestigationState.PENDING,
        trigger=trigger,
        created_at=now,
        scenario=scenario_of(trigger),
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
        await bus.publish(
            StepFinishedEvent(
                investigation_id=investigation.id,
                agent=step.agent,
                finding_count=len(outcome.findings),
            ),
            investigation_id=investigation.id,
        )

    verdict = aggregator.aggregate(investigation.id, findings, completed_steps)
    partial = any(s.status is not StepStatus.COMPLETE for s in completed_steps)

    investigation = investigation.model_copy(
        update={
            "state": InvestigationState.COMPLETED,
            "completed_at": datetime.now(UTC),
            "plan": completed_steps,
            "findings": findings,
            "verdict": verdict,
        }
    )
    await store.save(investigation)

    await bus.publish(
        VerdictReadyEvent(investigation_id=investigation.id, verdict=verdict),
        investigation_id=investigation.id,
    )
    await bus.publish(
        InvestigationCompletedEvent(
            investigation_id=investigation.id,
            state=InvestigationState.COMPLETED.value,
            partial=partial,
        ),
        investigation_id=investigation.id,
    )
    return investigation


async def get(investigation_id: UUID, *, store: InvestigationStore) -> Investigation | None:
    """Read one back. Absence is an answer, not an error."""
    return await store.get(investigation_id)
