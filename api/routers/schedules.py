"""The scheduled-trigger receiver: a measurement somebody configured to recur.

WHAT THIS IS FOR
------------------
Some questions are not incidents. "How is delivery health on checkout this
month" has no alert behind it and no pull request in front of it; it is asked
on a schedule, by something configured to ask. `TriggerKind.SCHEDULE` existed
for that and nothing produced one, so Themis - written, tested, and the agent
that answers it - was implemented and unreachable.

WHY THIS IS NOT "A SECOND WAY IN"
-----------------------------------
`api/routers/investigations.py` refuses a `POST /investigations` because it
would mint a run "with none of the classification a trigger carries". This
carries one: a named job, which the classifier maps to a domain, and the
subject the agent needs. It is a trigger receiver in the same sense as
`/webhooks/alertmanager` - it accepts one kind of inbound event and starts the
run that kind of event starts.

WHY AN UNKNOWN JOB IS A 422 AND NOT A 202
-------------------------------------------
The GitHub receiver accepts every event type and investigates two, because
GitHub sends dozens to a hook configured for everything and a red delivery log
for working correctly is worse than a quiet 202. A schedule is configured by
us. A job name nothing classifies is a misconfigured CronJob, and the person
who wrote it should find out from the response rather than from an
investigation that never appears.

WHO CALLS IT
--------------
Anything with an OPERATOR or ADMIN token - in the chart, a CronJob. Bearer auth
rather than a shared-secret header, because the caller is inside the
deployment and already has an identity, and that identity carries the tenant
the run belongs to.

WHAT IT DOES NOT NEED
-----------------------
Temporal. `core/orchestrator/dispatcher.py` names what would force durable
execution - steps that wait on the outside world, and retries that survive a
restart - and "something fires this at 06:00" is neither. A CronJob is a
scheduler. Temporal is for what happens after the trigger, and nothing here
changes that.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.auth.dependencies import Principal, Role, require
from api.routers._runs import gate_for, runner_for
from api.routers.investigations import get_store
from api.routers.webhooks import get_event_bus
from core.bus import EventBus
from core.contracts.events import TriggerReceivedEvent
from core.contracts.investigation import Trigger, TriggerKind
from core.orchestrator.classifier import SCHEDULED_JOBS
from core.store.investigations import InvestigationStore

router = APIRouter(prefix="/triggers", tags=["triggers"])


class ScheduledRun(BaseModel):
    """What a scheduler sends. Named job, and what the job is about."""

    job: str = Field(description="Which scheduled measurement, e.g. 'delivery-health'.")
    repository: str = Field(
        min_length=1,
        description="owner/repo. Every scheduled job today measures a repository.",
    )
    window_days: int = Field(
        default=28, ge=1, le=365, description="How far back the measurement looks."
    )


class ScheduledRunAccepted(BaseModel):
    investigation_id: UUID
    job: str
    accepted: bool = True


@router.post(
    "/schedule",
    response_model=ScheduledRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a scheduled measurement",
)
async def receive_schedule(
    request: Request,
    background: BackgroundTasks,
    payload: ScheduledRun,
    principal: Annotated[Principal, require(Role.OPERATOR, Role.ADMIN)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
    store: Annotated[InvestigationStore, Depends(get_store)],
) -> ScheduledRunAccepted:
    """Accept a scheduled job, open an Investigation, and say so on the bus.

    202 and a background task, as the other receivers: a CronJob's curl has a
    timeout, and a measurement that reads a month of pull requests can outlast
    it.
    """
    if payload.job not in SCHEDULED_JOBS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"no scheduled job named {payload.job!r}. Known: {sorted(SCHEDULED_JOBS)}. "
                "A schedule is configured by us, so an unknown name is a misconfiguration "
                "rather than an event to accept and ignore."
            ),
        )

    investigation_id = uuid4()
    trigger = Trigger(
        kind=TriggerKind.SCHEDULE,
        received_at=datetime.now(UTC),
        source=principal.subject,
        title=f"{payload.job} on {payload.repository} ({payload.window_days}d)",
        # Stored verbatim, as every receiver stores its payload: what the
        # scheduler asked is what the run should be able to show it was asked.
        payload=payload.model_dump(),
    )

    await bus.publish(
        TriggerReceivedEvent(investigation_id=investigation_id, trigger=trigger),
        investigation_id=investigation_id,
    )
    background.add_task(
        runner_for(request),
        trigger=trigger,
        investigation_id=investigation_id,
        store=store,
        bus=bus,
        gate=gate_for(request),
        tenant=principal.tenant,
    )
    return ScheduledRunAccepted(investigation_id=investigation_id, job=payload.job)
