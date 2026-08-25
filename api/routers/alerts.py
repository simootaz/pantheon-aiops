"""The Alertmanager receiver: an alert arrives, an Investigation begins.

Phase 1's headline is *"an alert produces a Finding"*, and this is the first
half of it. Alertmanager pushes here; Pantheon does not poll. That is
Alertmanager's own model - it owns grouping, inhibition and repeat intervals,
and a poller would fight all three.

SAME DISCIPLINE AS THE GITLAB HOOK
----------------------------------
Nothing here knows the simulator exists. `deploy/observability/prometheus/`
rules fire against simulator data and Alertmanager posts the result to this
same URL, precisely because a real Alertmanager will later post to it too. A
simulator-only route would mean the path exercised in development is not the
path exercised in production.

The payload is stored **verbatim** on the `Trigger`. Alertmanager's schema has
changed across versions and carries labels nobody has thought of a use for yet;
parsing it down to the fields we currently want would silently discard the rest,
and the discarded half is what an investigation usually turns out to need.

Returning 202 rather than 200 is deliberate, for the same reason as the GitLab
hook: the work has been accepted, not done.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from api.routers.investigations import get_store
from api.routers.webhooks import get_event_bus
from core.bus import EventBus
from core.config import get_settings
from core.contracts.events import TriggerReceivedEvent
from core.contracts.investigation import Trigger, TriggerKind
from core.orchestrator import for_manifest, investigate
from core.store.investigations import InvestigationStore

logger = logging.getLogger(__name__)


class InvestigationRunner(Protocol):
    """What the receiver hands an accepted alert to."""

    async def __call__(
        self,
        *,
        trigger: Trigger,
        investigation_id: UUID,
        store: InvestigationStore,
        bus: EventBus,
    ) -> None: ...


router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: Alertmanager sends `status: firing` or `status: resolved`. A resolved batch
#: is still worth recording - it is how an investigation learns the thing it is
#: looking at has stopped - so both are accepted and the distinction is kept.
FIRING = "firing"
RESOLVED = "resolved"


class AlertsAccepted(BaseModel):
    """What Alertmanager gets back: enough to correlate, nothing more."""

    investigation_id: UUID
    accepted: bool = True
    status: str
    alert_count: int


def _verify_token(supplied: str | None) -> None:
    """Check the shared secret, when one is configured.

    `compare_digest` rather than `==`, because a plain comparison returns early
    on the first differing byte and leaks the secret's prefix to anyone who can
    time the response.
    """
    configured = get_settings().alertmanager.webhook_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        return
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook token"
        )


def _title_for(payload: dict[str, Any]) -> str:
    """One line, from whichever fields this Alertmanager version actually sent."""
    common = payload.get("commonLabels") or {}
    alerts = payload.get("alerts") or []
    name = common.get("alertname") or (
        (alerts[0].get("labels") or {}).get("alertname") if alerts else None
    )
    subject = common.get("service") or common.get("instance") or common.get("job") or ""
    state = str(payload.get("status", FIRING))

    if not name:
        return f"alertmanager: {len(alerts)} alert(s) {state}"
    return f"{name} {state}" + (f" on {subject}" if subject else "")


@router.post(
    "/alertmanager",
    response_model=AlertsAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive an Alertmanager notification",
)
async def receive_alertmanager(
    request: Request,
    background: BackgroundTasks,
    bus: Annotated[EventBus, Depends(get_event_bus)],
    store: Annotated[InvestigationStore, Depends(get_store)],
    token: Annotated[str | None, Header(alias="X-Pantheon-Token")] = None,
) -> AlertsAccepted:
    """Accept a notification, open an Investigation, and say so on the bus.

    202 and a background task, not a synchronous run: Alertmanager retries a
    slow receiver, and an investigation that takes seconds would be started
    twice. The returned `investigation_id` is the one Zeus will write, so a
    caller can poll `GET /investigations/{id}` and see 404 until it exists.
    """
    _verify_token(token)

    try:
        payload: dict[str, Any] = await request.json()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="body is not valid JSON"
        ) from error

    if not isinstance(payload, dict) or "alerts" not in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expected an Alertmanager notification with an `alerts` array",
        )

    alerts = payload.get("alerts") or []
    investigation_id = uuid4()
    trigger = Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title=_title_for(payload),
        payload=payload,
    )

    await bus.publish(
        TriggerReceivedEvent(investigation_id=investigation_id, trigger=trigger),
        investigation_id=investigation_id,
    )

    # A resolved batch is recorded and not investigated. "This stopped" is worth
    # knowing and is not a reason to go looking for a fault that has ended.
    if str(payload.get("status", FIRING)) == FIRING:
        background.add_task(
            _runner(request),
            trigger=trigger,
            investigation_id=investigation_id,
            store=store,
            bus=bus,
        )

    return AlertsAccepted(
        investigation_id=investigation_id,
        status=str(payload.get("status", FIRING)),
        alert_count=len(alerts),
    )


def _runner(request: Request) -> InvestigationRunner:
    """What actually runs an accepted alert, from application state.

    Injectable because the default reaches Prometheus and Postgres, and a unit
    test that exercises this endpoint would otherwise open sockets as a side
    effect of asserting a 202. Substituting a recorder keeps those tests offline
    and makes "an alert schedules an investigation" an assertion rather than a
    consequence nobody checks.
    """
    runner: InvestigationRunner | None = getattr(request.app.state, "investigation_runner", None)
    return runner if runner is not None else _investigate


async def _investigate(
    *,
    trigger: Trigger,
    investigation_id: UUID,
    store: InvestigationStore,
    bus: EventBus,
) -> None:
    """Run Zeus for an accepted alert.

    Failures are logged and swallowed rather than raised: this runs after the
    response, so an exception here reaches nobody. Zeus itself records a FAILED
    Investigation for anything it can attribute, which is the path a reader will
    actually see.
    """
    try:
        await investigate(
            trigger,
            store=store,
            bus=bus,
            toolset=for_manifest,
            investigation_id=investigation_id,
        )
    except Exception:
        logger.exception("investigation %s failed", investigation_id)
