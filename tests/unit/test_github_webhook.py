"""The GitHub webhook endpoint: what it verifies, and over which bytes.

The property that carries this file: GitHub signs the RAW body. A handler that
verified a re-serialisation of the parsed payload would compute a signature over
different bytes - different whitespace, different key order - and reject every
genuine delivery. That version at least fails loudly. The worse one accepts a
body it never verified.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.bus import InMemoryEventBus
from core.config import get_settings
from core.contracts.investigation import TriggerKind
from core.orchestrator.classifier import classify

SECRET = "a-shared-secret"
REPO = "acme/checkout"

PULL_REQUEST: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"number": 12},
    "repository": {"full_name": REPO},
}
FAILED_RUN: dict[str, Any] = {
    "action": "completed",
    "workflow_run": {"id": 99, "conclusion": "failure"},
    "repository": {"full_name": REPO},
}


def _signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _body(payload: dict[str, Any]) -> bytes:
    """Serialised the way an HTTP client would send it - and NOT the way
    `json.dumps` on the parsed dict would produce it later.

    The separators differ from Python's default on purpose: that difference is
    exactly what a handler verifying a re-serialisation would trip over, so the
    fixture has to carry it or the test proves nothing.
    """
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def client(bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    with TestClient(create_app(event_bus=bus)) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def unverified(bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """No secret configured, which is the local-development posture."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app(event_bus=bus)) as test_client:
        yield test_client
    get_settings.cache_clear()


def _post(client: TestClient, payload: dict[str, Any], event: str, sign: bool = True) -> Any:
    body = _body(payload)
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if sign:
        headers["X-Hub-Signature-256"] = _signed(body)
    return client.post("/webhooks/github", content=body, headers=headers)


# --- the signature is over the bytes GitHub sent ------------------------------------------


def test_a_correctly_signed_delivery_is_accepted(client: TestClient) -> None:
    response = _post(client, PULL_REQUEST, "pull_request")

    assert response.status_code == 202
    assert response.json()["event"] == "pull_request"


def test_the_signature_is_computed_over_the_raw_body_not_a_reserialisation(
    client: TestClient,
) -> None:
    """The whole point. `json.dumps(payload)` on the parsed dict produces
    different bytes - Python's default separators include spaces - so a handler
    verifying that would reject this delivery, which is correctly signed.
    """
    body = _body(PULL_REQUEST)
    assert body != json.dumps(PULL_REQUEST).encode(), (
        "the fixture must differ from a naive re-serialisation, or it proves nothing"
    )

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signed(body),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 202


def test_an_unsigned_delivery_is_refused_when_a_secret_is_configured(
    client: TestClient,
) -> None:
    """An unverified webhook endpoint is a way for anyone to start an
    investigation against any repository name they care to type."""
    response = _post(client, PULL_REQUEST, "pull_request", sign=False)

    assert response.status_code == 401


def test_a_signature_from_the_wrong_secret_is_refused(client: TestClient) -> None:
    body = _body(PULL_REQUEST)

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signed(body, secret="not-the-secret"),
        },
    )

    assert response.status_code == 401


def test_a_signature_for_a_different_body_is_refused(client: TestClient) -> None:
    """The replay case: a valid signature lifted from one delivery and attached
    to another."""
    response = client.post(
        "/webhooks/github",
        content=_body(FAILED_RUN),
        headers={
            "X-GitHub-Event": "workflow_run",
            "X-Hub-Signature-256": _signed(_body(PULL_REQUEST)),
        },
    )

    assert response.status_code == 401


def test_no_configured_secret_accepts_anything(unverified: TestClient) -> None:
    """The local-development posture, stated rather than implied. `.env.example`
    says what it costs anywhere a real GitHub can reach."""
    response = _post(unverified, PULL_REQUEST, "pull_request", sign=False)

    assert response.status_code == 202


# --- what reaches the bus ----------------------------------------------------------------


def test_the_payload_is_stored_verbatim(client: TestClient, bus: InMemoryEventBus) -> None:
    """An agent that needs a field nobody anticipated can still find it, and a
    payload reshaped on the way in is a payload we cannot replay."""
    _post(client, PULL_REQUEST, "pull_request")

    (envelope,) = bus.published
    trigger = envelope.event.trigger  # type: ignore[union-attr]
    assert trigger.payload == PULL_REQUEST
    assert trigger.kind is TriggerKind.WEBHOOK
    assert trigger.source == "github"


def test_the_published_trigger_classifies_to_the_right_agent(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """End to end through the two halves that have to agree: what the endpoint
    builds and what the classifier reads. A title-only trigger would publish
    fine and route nowhere."""
    _post(client, PULL_REQUEST, "pull_request")
    _post(client, FAILED_RUN, "workflow_run")

    routed = [classify(envelope.event.trigger).domains for envelope in bus.published]  # type: ignore[union-attr]
    assert routed == [("manifest_review",), ("ci_triage",)]


def test_a_title_is_built_from_the_fields_the_hook_carries(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    _post(client, PULL_REQUEST, "pull_request")
    _post(client, FAILED_RUN, "workflow_run")

    titles = [envelope.event.trigger.title for envelope in bus.published]  # type: ignore[union-attr]
    assert titles[0] == f"pull request #12 opened on {REPO}"
    assert titles[1] == f"workflow run 99 failure on {REPO}"


def test_an_event_nobody_acts_on_is_still_accepted(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """GitHub sends dozens of event types to a hook configured for everything.
    202 for one nobody reads is honest; a 400 would make a green delivery log go
    red for working correctly."""
    response = _post(client, {"repository": {"full_name": REPO}}, "star")

    assert response.status_code == 202
    assert len(bus.published) == 1


# --- malformed bodies --------------------------------------------------------------------


def test_a_body_that_is_not_json_is_refused_after_the_signature_check(
    client: TestClient,
) -> None:
    """Order matters: verify first, parse second. Parsing an unverified body is
    running a parser on input from anyone who found the URL."""
    body = b"{not json"

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": _signed(body)},
    )

    assert response.status_code == 400
    assert "not JSON" in response.json()["detail"]


def test_a_json_array_is_refused(client: TestClient) -> None:
    """`Trigger.payload` is a mapping. A list would fail validation deeper in,
    with a message about a contract rather than about the request."""
    body = b"[1, 2, 3]"

    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": _signed(body)},
    )

    assert response.status_code == 400
    assert "JSON object" in response.json()["detail"]


def test_an_unsigned_malformed_body_is_a_401_and_not_a_400(client: TestClient) -> None:
    """Which is the observable proof that verification runs first. A 400 here
    would mean the parser saw the body before the signature did."""
    response = client.post(
        "/webhooks/github", content=b"{not json", headers={"X-GitHub-Event": "push"}
    )

    assert response.status_code == 401


# --- the trigger reaches Zeus, not only the bus ------------------------------------------


class _Recorder:
    """Stands in for the runner, so this stays offline."""

    def __init__(self) -> None:
        self.runs: list[Any] = []

    async def __call__(self, *, trigger: Any, investigation_id: Any, store: Any, bus: Any) -> None:
        self.runs.append(trigger)


@pytest.fixture
def scheduled(
    bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, _Recorder]]:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    get_settings.cache_clear()
    recorder = _Recorder()
    app = create_app(event_bus=bus)
    app.state.investigation_runner = recorder
    with TestClient(app) as test_client:
        yield test_client, recorder
    get_settings.cache_clear()


def test_a_pull_request_starts_an_investigation(
    scheduled: tuple[TestClient, _Recorder],
) -> None:
    """Before this, a pull request reached the bus and no agent ever saw it -
    even though the classifier knew exactly what to hand Aegis."""
    client, recorder = scheduled

    response = _post(client, PULL_REQUEST, "pull_request")

    assert response.status_code == 202
    assert response.json()["investigating"] is True
    assert len(recorder.runs) == 1


def test_a_failed_workflow_run_starts_an_investigation(
    scheduled: tuple[TestClient, _Recorder],
) -> None:
    client, recorder = scheduled

    assert _post(client, FAILED_RUN, "workflow_run").json()["investigating"] is True
    assert len(recorder.runs) == 1


def test_a_green_workflow_run_starts_nothing(scheduled: tuple[TestClient, _Recorder]) -> None:
    """The control, and the point of `investigating` being on the response: a
    202 alone cannot say which of the two happened."""
    client, recorder = scheduled
    green = {**FAILED_RUN, "workflow_run": {"id": 99, "conclusion": "success"}}

    response = _post(client, green, "workflow_run")

    assert response.status_code == 202
    assert response.json()["investigating"] is False
    assert recorder.runs == []


def test_an_event_nobody_acts_on_starts_nothing(
    scheduled: tuple[TestClient, _Recorder],
) -> None:
    """A hook configured for every event sends dozens of types. Starting a run
    for each would fill the store with investigations that found nothing
    because there was nothing to look at."""
    client, recorder = scheduled

    response = _post(client, {"repository": {"full_name": REPO}}, "star")

    assert response.json()["investigating"] is False
    assert recorder.runs == []


def test_the_scheduled_trigger_is_the_one_that_was_published(
    scheduled: tuple[TestClient, _Recorder], bus: InMemoryEventBus
) -> None:
    """One trigger, not two. A receiver that built a second one for the runner
    would publish a different object than it investigated, and the two would
    drift the first time either was edited."""
    client, recorder = scheduled

    _post(client, PULL_REQUEST, "pull_request")

    (envelope,) = bus.published
    assert recorder.runs[0] == envelope.event.trigger  # type: ignore[union-attr]
