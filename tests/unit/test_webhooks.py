"""The GitLab webhook endpoint, and the bus event it produces.

The endpoint carries no simulator-specific handling, so these tests use
GitLab's own payload shapes. If they were written against something the
simulator emits and GitLab does not, the endpoint would be verified against a
fiction.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.bus import InMemoryEventBus
from core.config import get_settings
from core.contracts.events import TriggerReceivedEvent
from core.store.investigations import InMemoryInvestigationStore
from tests.mechanism import read_data

PIPELINE_PAYLOAD: dict[str, Any] = {
    "object_kind": "pipeline",
    "object_attributes": {
        "id": 4711,
        "ref": "main",
        "sha": "1f0c2d",
        "status": "failed",
        "duration": 312,
    },
    "project": {"path_with_namespace": "acme/checkout", "web_url": "https://gitlab/acme/checkout"},
    "builds": [
        {"id": 1, "name": "unit", "status": "success"},
        {"id": 2, "name": "integration", "status": "failed"},
    ],
}

MERGE_REQUEST_PAYLOAD: dict[str, Any] = {
    "object_kind": "merge_request",
    "object_attributes": {
        "iid": 91,
        "title": "Bump connection pool size",
        "state": "opened",
        "action": "open",
        "source_branch": "pool-size",
        "target_branch": "main",
    },
    "project": {"path_with_namespace": "acme/checkout"},
}


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def scheduled() -> list[UUID]:
    """Investigations the receiver handed off, without running any of them."""
    return []


@pytest.fixture
def client(bus: InMemoryEventBus, scheduled: list[UUID]) -> Iterator[TestClient]:
    """An app with nothing behind it that opens a socket.

    The real runner reaches Prometheus and Postgres. `TestClient` executes
    background tasks inline, so leaving it in place would have every alert test
    quietly performing network I/O - and on this platform a closed loopback port
    does not refuse promptly, so the failure mode is a hang rather than an error.
    """

    async def record(*, investigation_id: UUID, **_: object) -> None:
        scheduled.append(investigation_id)

    app = create_app(event_bus=bus, investigation_store=InMemoryInvestigationStore())
    app.state.investigation_runner = record
    with TestClient(app) as test_client:
        yield test_client


def test_a_pipeline_hook_produces_a_bus_event(client: TestClient, bus: InMemoryEventBus) -> None:
    response = client.post(
        "/webhooks/gitlab",
        json=PIPELINE_PAYLOAD,
        headers={"X-Gitlab-Event": "Pipeline Hook"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] is True

    assert len(bus.published) == 1
    event = bus.published[0].event
    assert isinstance(event, TriggerReceivedEvent)
    assert str(event.investigation_id) == body["investigation_id"]


def test_the_trigger_carries_the_payload_verbatim(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """A payload we reshaped on the way in is a payload we cannot replay."""
    client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )

    event = bus.published[0].event
    assert isinstance(event, TriggerReceivedEvent)
    trigger = event.trigger
    assert trigger.payload == PIPELINE_PAYLOAD
    assert trigger.source == "gitlab"
    assert trigger.kind.value == "webhook"


def test_the_title_is_readable_for_both_hook_types(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )
    client.post(
        "/webhooks/gitlab",
        json=MERGE_REQUEST_PAYLOAD,
        headers={"X-Gitlab-Event": "Merge Request Hook"},
    )

    events = [envelope.event for envelope in bus.published]
    assert all(isinstance(event, TriggerReceivedEvent) for event in events)
    titles = [event.trigger.title for event in events if isinstance(event, TriggerReceivedEvent)]
    assert titles[0] == "pipeline 4711 failed on acme/checkout@main"
    assert titles[1] == "merge request !91 open on acme/checkout"


def test_sequence_numbers_are_per_investigation(client: TestClient, bus: InMemoryEventBus) -> None:
    """Replay depends on order, so it is assigned by the bus, not the caller."""
    client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )
    client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )

    # Two different investigations, so both start at zero rather than 0 and 1.
    assert [envelope.sequence for envelope in bus.published] == [0, 0]
    ids = {
        envelope.event.investigation_id
        for envelope in bus.published
        if isinstance(envelope.event, TriggerReceivedEvent)
    }
    assert len(ids) == 2


def test_an_unknown_hook_type_is_still_accepted(client: TestClient, bus: InMemoryEventBus) -> None:
    """A webhook that 400s on an event it ignores teaches operators to disable it."""
    response = client.post(
        "/webhooks/gitlab",
        json={"object_kind": "release", "project": {"path_with_namespace": "acme/checkout"}},
        headers={"X-Gitlab-Event": "Release Hook"},
    )
    assert response.status_code == 202
    assert len(bus.published) == 1


def test_the_token_is_required_when_configured(
    client: TestClient, bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings are cached, so changing the environment means clearing them.

    `get_settings()` is `lru_cache`d on purpose: configuration is read once and
    every caller sees the same values. The cost is that a test which sets a
    variable after first use must invalidate it, or it asserts against the
    settings the process started with.
    """
    monkeypatch.setenv("GITLAB_WEBHOOK_TOKEN", "s3cret-token-value")
    get_settings.cache_clear()

    rejected = client.post(
        "/webhooks/gitlab",
        json=PIPELINE_PAYLOAD,
        headers={"X-Gitlab-Event": "Pipeline Hook", "X-Gitlab-Token": "wrong"},
    )
    assert rejected.status_code == 401
    assert bus.published == []

    missing = client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )
    assert missing.status_code == 401

    accepted = client.post(
        "/webhooks/gitlab",
        json=PIPELINE_PAYLOAD,
        headers={"X-Gitlab-Event": "Pipeline Hook", "X-Gitlab-Token": "s3cret-token-value"},
    )
    assert accepted.status_code == 202
    assert len(bus.published) == 1


def test_no_token_configured_means_no_token_required(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local development must not need a secret to receive a webhook."""
    monkeypatch.delenv("GITLAB_WEBHOOK_TOKEN", raising=False)
    assert "GITLAB_WEBHOOK_TOKEN" not in os.environ

    response = client.post(
        "/webhooks/gitlab", json=PIPELINE_PAYLOAD, headers={"X-Gitlab-Event": "Pipeline Hook"}
    )
    assert response.status_code == 202


def test_the_endpoint_has_no_simulator_specific_handling() -> None:
    """Real GitLab must hit the same path the simulator does.

    A bypass, a test mode, or a header only the simulator sets would mean the
    path exercised in development is not the path exercised in production.

    Checked against the *code*, with docstrings and comments stripped. The
    module's own docstring explains at length that it is not a simulator
    endpoint, and a naive text search fires on that explanation - the same
    documentation-versus-mechanism confusion that made three Phase 0 guards
    unable to fail.
    """
    import ast
    from pathlib import Path

    source = read_data(Path(__file__).resolve().parents[2] / "api" / "routers" / "webhooks.py")

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = node.body
        first = body[0] if body else None
        is_docstring = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        if is_docstring:
            node.body = body[1:] or [ast.Pass()]

    executable = ast.unparse(tree).lower()

    for forbidden in ("simulator", "x-pantheon-sim", "is_simulated", "test_mode"):
        assert forbidden not in executable, (
            f"webhooks.py references {forbidden!r} in executable code; the endpoint "
            "must not know the simulator exists"
        )


# --- the Alertmanager receiver ------------------------------------------------


def _alertmanager_body(status: str = "firing", alerts: int = 1) -> dict[str, object]:
    return {
        "version": "4",
        "status": status,
        "receiver": "pantheon",
        "commonLabels": {"alertname": "CheckoutErrorRateHigh", "service": "checkout"},
        "alerts": [
            {
                "status": status,
                "labels": {"alertname": "CheckoutErrorRateHigh", "service": "checkout"},
                "startsAt": "2026-08-18T12:00:00Z",
                "fingerprint": f"aa{index:014x}",
            }
            for index in range(alerts)
        ],
    }


def test_an_alertmanager_notification_opens_an_investigation(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """Phase 1's headline, first half: an alert arrives and something begins."""
    response = client.post("/webhooks/alertmanager", json=_alertmanager_body())

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["alert_count"] == 1

    published = [envelope.event for envelope in bus.published]
    assert [event.type for event in published] == ["trigger_received"]
    event = published[0]
    assert isinstance(event, TriggerReceivedEvent)
    assert event.trigger.source == "alertmanager"


def test_a_resolved_notification_is_accepted_too(client: TestClient, bus: InMemoryEventBus) -> None:
    """Resolved is how an investigation learns its subject stopped."""
    response = client.post("/webhooks/alertmanager", json=_alertmanager_body("resolved"))
    assert response.status_code == 202
    assert response.json()["status"] == "resolved"
    assert len(bus.published) == 1


def test_the_alertmanager_payload_is_stored_verbatim(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """Its schema varies by version; parsing it down discards the useful half."""
    payload = _alertmanager_body(alerts=3)
    client.post("/webhooks/alertmanager", json=payload)
    event = bus.published[0].event
    assert isinstance(event, TriggerReceivedEvent)
    assert event.trigger.payload == payload


def test_a_body_without_alerts_is_rejected(client: TestClient, bus: InMemoryEventBus) -> None:
    """400 rather than 202: accepting anything makes the endpoint a black hole."""
    assert client.post("/webhooks/alertmanager", json={"status": "firing"}).status_code == 400
    assert bus.published == []


def test_a_title_is_derived_even_from_a_sparse_payload(
    client: TestClient, bus: InMemoryEventBus
) -> None:
    """Alertmanager can omit commonLabels; the title must survive that."""
    client.post("/webhooks/alertmanager", json={"status": "firing", "alerts": []})
    event = bus.published[0].event
    assert isinstance(event, TriggerReceivedEvent)
    assert "alertmanager" in event.trigger.title


def test_the_alertmanager_token_is_required_when_configured(
    client: TestClient, bus: InMemoryEventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same discipline as the GitLab hook, including the constant-time compare."""
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", "s3cret-alert-token")
    get_settings.cache_clear()

    rejected = client.post(
        "/webhooks/alertmanager",
        json=_alertmanager_body(),
        headers={"X-Pantheon-Token": "wrong"},
    )
    assert rejected.status_code == 401
    assert bus.published == []

    accepted = client.post(
        "/webhooks/alertmanager",
        json=_alertmanager_body(),
        headers={"X-Pantheon-Token": "s3cret-alert-token"},
    )
    assert accepted.status_code == 202


def test_a_firing_alert_schedules_an_investigation(
    client: TestClient, scheduled: list[UUID]
) -> None:
    """The 202 hands back the id Zeus will write, not one nothing creates."""
    response = client.post(
        "/webhooks/alertmanager",
        json={
            "status": "firing",
            "alerts": [{"labels": {"alertname": "CheckoutErrorRateHigh"}}],
        },
    )

    assert response.status_code == 202, response.text
    promised = UUID(response.json()["investigation_id"])
    assert scheduled == [promised], (
        "the receiver returned an investigation id it did not hand to anyone, so a "
        "caller polling that id would wait forever"
    )


def test_a_resolved_alert_is_recorded_and_not_investigated(
    client: TestClient, scheduled: list[UUID], bus: InMemoryEventBus
) -> None:
    """ "This stopped" is worth knowing and is not a reason to go looking.

    Still published, so a run that is watching learns the thing it is looking at
    has ended. Not investigated, because the fault is over.
    """
    response = client.post(
        "/webhooks/alertmanager",
        json={
            "status": "resolved",
            "alerts": [{"labels": {"alertname": "CheckoutErrorRateHigh"}}],
        },
    )

    assert response.status_code == 202, response.text
    assert scheduled == [], "a resolved alert opened an investigation into a finished fault"
    assert any(e.event.type == "trigger_received" for e in bus.published), (
        "a resolved alert was dropped rather than recorded"
    )
