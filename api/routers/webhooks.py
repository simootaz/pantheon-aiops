"""Inbound webhooks. Currently GitLab; the shape generalises.

WHAT THIS IS NOT
----------------
It is not a simulator endpoint. `simulator/pipeline_generator.py` posts
GitLab-shaped payloads here precisely *because* real GitLab will post to the
same URL later — a simulator-specific route would mean the path exercised in
development is not the path exercised in production, which makes the simulator
worth less the more it is relied on.

So nothing here knows the simulator exists, and there is no bypass, no test
mode, and no header the simulator sets that GitLab would not.

WHAT IT DOES
------------
Parses the payload into a `Trigger`, creates an `Investigation` in PENDING, and
publishes `TriggerReceivedEvent` onto the internal bus. It does not plan or
dispatch: Zeus does that at Phase 2, reading from the bus.

Returning 202 rather than 200 is deliberate. The work has been accepted, not
done, and a webhook sender that reads 200 as "handled" will not retry when it
should.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from core.bus import EventBus
from core.config import get_settings
from core.contracts.events import TriggerReceivedEvent
from core.contracts.investigation import Trigger, TriggerKind

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: GitLab event headers this endpoint understands. Anything else is accepted at
#: the HTTP layer and ignored, because a webhook that 400s on an event type it
#: does not care about teaches operators to disable the integration.
PIPELINE_HOOK = "Pipeline Hook"
MERGE_REQUEST_HOOK = "Merge Request Hook"
UNDERSTOOD_HOOKS = frozenset({PIPELINE_HOOK, MERGE_REQUEST_HOOK})


class WebhookAccepted(BaseModel):
    """What the sender gets back: enough to correlate, nothing more."""

    investigation_id: UUID
    accepted: bool = True
    event: str


def get_event_bus(request: Request) -> EventBus:
    """The bus, from application state, so tests can substitute one."""
    bus: EventBus | None = getattr(request.app.state, "event_bus", None)
    if bus is None:  # pragma: no cover - the app factory always sets it
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="event bus is not configured",
        )
    return bus


def _verify_token(supplied: str | None) -> None:
    """Check the shared secret, when one is configured.

    Compared with `compare_digest` rather than `==`: a plain comparison returns
    early on the first differing byte, which leaks the secret's prefix to anyone
    who can time the response.
    """
    configured = get_settings().gitlab.webhook_token
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        return
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook token"
        )


def _title_for(event: str, payload: dict[str, Any]) -> str:
    """A one-line description, from whichever fields the hook actually carries."""
    attributes = payload.get("object_attributes") or {}
    project = (payload.get("project") or {}).get("path_with_namespace", "unknown")

    if event == PIPELINE_HOOK:
        return (
            f"pipeline {attributes.get('id', '?')} {attributes.get('status', '?')} "
            f"on {project}@{attributes.get('ref', '?')}"
        )
    if event == MERGE_REQUEST_HOOK:
        return (
            f"merge request !{attributes.get('iid', '?')} "
            f"{attributes.get('action', '?')} on {project}"
        )
    return f"{event} on {project}"


@router.post(
    "/gitlab",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAccepted,
    summary="Accept a GitLab webhook",
)
async def gitlab_webhook(
    payload: dict[str, Any],
    bus: Annotated[EventBus, Depends(get_event_bus)],
    x_gitlab_event: Annotated[str | None, Header()] = None,
    x_gitlab_token: Annotated[str | None, Header()] = None,
) -> WebhookAccepted:
    """Accept a GitLab hook, create an Investigation, and publish the trigger."""
    _verify_token(x_gitlab_token)

    event = x_gitlab_event or payload.get("object_kind", "unknown")
    investigation_id = uuid4()

    trigger = Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=datetime.now(UTC),
        source="gitlab",
        title=_title_for(event, payload),
        # Stored verbatim. An agent that needs a field nobody anticipated can
        # still find it, and a payload we reshaped on the way in is a payload we
        # cannot replay.
        payload=payload,
    )

    await bus.publish(
        TriggerReceivedEvent(investigation_id=investigation_id, trigger=trigger),
        investigation_id=investigation_id,
    )

    return WebhookAccepted(investigation_id=investigation_id, event=event)


#: The events this endpoint acts on. Everything else is accepted and published
#: without an investigation - GitHub sends dozens of event types to a hook
#: configured for "everything", and 202 for an event nobody reads is honest
#: while a 400 would make a green delivery log go red for working correctly.
GITHUB_ACTED_ON = ("pull_request", "workflow_run")


def _verify_signature(body: bytes, supplied: str | None) -> None:
    """Check GitHub's HMAC over the RAW body, when a secret is configured.

    The raw bytes, not the parsed payload. Re-serialising a dict changes
    whitespace and key order, and the signature is over what GitHub actually
    sent - so a handler that verified `json.dumps(payload)` would reject every
    genuine delivery and pass none, which at least fails loudly. The worse
    version accepts a body it did not verify.

    `compare_digest` rather than `==`, the same reason as the GitLab token: a
    plain comparison returns early on the first differing byte, which leaks the
    digest prefix to anyone who can time the response.
    """
    configured = get_settings().github.webhook_secret
    secret = configured.get_secret_value() if configured else ""
    if not secret:
        return

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook signature",
        )


def _github_title(event: str, payload: dict[str, Any]) -> str:
    """A one-line description, from whichever fields the hook actually carries."""
    repository = (payload.get("repository") or {}).get("full_name", "unknown")

    if event == "pull_request":
        change = payload.get("pull_request") or {}
        return (
            f"pull request #{change.get('number', '?')} "
            f"{payload.get('action', '?')} on {repository}"
        )
    if event == "workflow_run":
        run = payload.get("workflow_run") or {}
        return f"workflow run {run.get('id', '?')} {run.get('conclusion', '?')} on {repository}"
    return f"{event} on {repository}"


@router.post(
    "/github",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAccepted,
    summary="Accept a GitHub webhook",
)
async def github_webhook(
    request: Request,
    bus: Annotated[EventBus, Depends(get_event_bus)],
    x_github_event: Annotated[str | None, Header()] = None,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> WebhookAccepted:
    """Accept a GitHub hook, verify its signature, and publish the trigger.

    Takes the `Request` rather than a parsed body, because the signature is over
    the raw bytes. FastAPI would happily hand over a `dict[str, Any]` and the
    verification would then be against a re-serialisation of it - a different
    string, and a check that cannot pass.

    202 rather than a synchronous run: GitHub times out a hook at 10 seconds and
    retries, and an investigation that took longer would be started twice.
    """
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as broken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"webhook body is not JSON: {broken}",
        ) from broken
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook body is not a JSON object",
        )

    event = x_github_event or "unknown"
    investigation_id = uuid4()

    trigger = Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=datetime.now(UTC),
        source="github",
        title=_github_title(event, payload),
        # Stored verbatim, the same as GitLab's. An agent that needs a field
        # nobody anticipated can still find it, and a payload we reshaped on the
        # way in is a payload we cannot replay.
        payload=payload,
    )

    await bus.publish(
        TriggerReceivedEvent(investigation_id=investigation_id, trigger=trigger),
        investigation_id=investigation_id,
    )

    return WebhookAccepted(investigation_id=investigation_id, event=event)


# TODO: Phase 4 - route webhook triggers to Zeus rather than only publishing.
#
# Both endpoints publish a TriggerReceivedEvent and stop. `POST
# /webhooks/alertmanager` runs an investigation in a BackgroundTask, and these
# two do not - so a pull request reaches the bus and no agent ever sees it,
# even though `classifier.subject_of` now knows exactly what to hand Aegis.
#
# It is one call. What it needs first is a decision about the store: the alert
# receiver writes the Investigation before returning the id, and a caller
# polling for a run that was only published would poll forever.
