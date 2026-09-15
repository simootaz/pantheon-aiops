"""The scheduled-trigger receiver, and the way in it gives Themis.

`TriggerKind.SCHEDULE` existed and nothing produced one. Themis - written,
tested, and the agent that answers a scheduled question - was registered
`dispatchable=False` with a comment saying nothing could schedule anything
until Temporal landed. `dispatcher.py` names what would force Temporal, and a
CronJob firing a trigger is not on the list.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth.dependencies import _principals
from api.main import create_app
from core.bus import InMemoryEventBus
from core.config import get_settings
from core.contracts.investigation import Trigger, TriggerKind
from core.orchestrator import planner
from core.orchestrator.classifier import SCHEDULED_JOBS, classify, scheduled_job_of, subject_of


class _Recorder:
    """Stands in for the runner. Named parameters, so a dropped one is a failure."""

    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        trigger: Any,
        investigation_id: Any,
        store: Any,
        bus: Any,
        gate: Any = None,
        tenant: str = "default",
    ) -> None:
        self.runs.append({"trigger": trigger, "gate": gate, "tenant": tenant})


@pytest.fixture
def receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, _Recorder, InMemoryEventBus]]:
    monkeypatch.setenv(
        "PANTHEON_API_TOKENS",
        "cron:operator@globex=op-token;viewer:viewer@globex=view-token",
    )
    get_settings.cache_clear()
    _principals.cache_clear()
    bus = InMemoryEventBus()
    recorder = _Recorder()
    app = create_app(event_bus=bus)
    app.state.investigation_runner = recorder
    try:
        with TestClient(app) as client:
            yield client, recorder, bus
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


def _post(client: TestClient, body: dict[str, Any], token: str = "op-token") -> Any:
    return client.post(
        "/triggers/schedule", json=body, headers={"Authorization": f"Bearer {token}"}
    )


# --- the receiver ---------------------------------------------------------------------


def test_a_known_job_starts_a_run(receiver: tuple[TestClient, _Recorder, InMemoryEventBus]) -> None:
    client, recorder, bus = receiver

    response = _post(client, {"job": "delivery-health", "repository": "acme/checkout"})

    assert response.status_code == 202, response.text
    assert response.json()["job"] == "delivery-health"
    (run,) = recorder.runs
    assert run["trigger"].kind is TriggerKind.SCHEDULE
    assert run["trigger"].payload["repository"] == "acme/checkout"
    assert [e.event.type for e in bus.published] == ["trigger_received"]


def test_the_run_belongs_to_the_callers_tenant(
    receiver: tuple[TestClient, _Recorder, InMemoryEventBus],
) -> None:
    """The one receiver with an identity passes it on.

    Alertmanager and GitHub carry none and land in the default tenant. A
    scheduled run has a principal, and dropping its tenant on the floor would
    file globex's delivery measurement where every other tenant can read it.
    """
    client, recorder, _ = receiver

    _post(client, {"job": "delivery-health", "repository": "acme/checkout"})

    assert recorder.runs[0]["tenant"] == "globex"


def test_the_run_is_given_the_approval_gate(
    receiver: tuple[TestClient, _Recorder, InMemoryEventBus],
) -> None:
    """Same as the webhook: a run with no gate has nowhere to put a remediation."""
    client, recorder, _ = receiver

    _post(client, {"job": "delivery-health", "repository": "acme/checkout"})

    assert recorder.runs[0]["gate"] is not None


def test_an_unknown_job_is_refused_not_accepted_and_ignored(
    receiver: tuple[TestClient, _Recorder, InMemoryEventBus],
) -> None:
    """422, naming the known jobs.

    GitHub's receiver accepts everything because GitHub sends everything. A
    schedule is configured by us, and a typo in a CronJob should come back in
    the response rather than as an investigation that never appears.
    """
    client, recorder, bus = receiver

    response = _post(client, {"job": "delivery-helth", "repository": "acme/checkout"})

    assert response.status_code == 422
    assert "delivery-health" in response.json()["detail"]
    assert recorder.runs == []
    assert bus.published == [], "a refused schedule was announced on the bus"


def test_a_viewer_cannot_schedule(receiver: tuple[TestClient, _Recorder, InMemoryEventBus]) -> None:
    """Starting a run is an action. VIEWER reads."""
    client, recorder, _ = receiver

    response = _post(
        client, {"job": "delivery-health", "repository": "acme/checkout"}, "view-token"
    )

    assert response.status_code == 403
    assert recorder.runs == []


def test_no_token_is_a_401(receiver: tuple[TestClient, _Recorder, InMemoryEventBus]) -> None:
    client, _, _ = receiver

    assert (
        client.post(
            "/triggers/schedule", json={"job": "delivery-health", "repository": "a/b"}
        ).status_code
        == 401
    )


def test_a_repository_is_required(receiver: tuple[TestClient, _Recorder, InMemoryEventBus]) -> None:
    """Themis refuses a run with no repository. Refusing it here, at the schedule,
    is the same refusal one step earlier and one response nearer the person
    who misconfigured it."""
    client, recorder, _ = receiver

    assert _post(client, {"job": "delivery-health"}).status_code == 422
    assert _post(client, {"job": "delivery-health", "repository": ""}).status_code == 422
    assert recorder.runs == []


# --- the classifier -------------------------------------------------------------------


def _schedule(**payload: Any) -> Trigger:
    return Trigger(
        kind=TriggerKind.SCHEDULE,
        received_at=datetime.now(UTC),
        source="cron",
        title="t",
        payload={"job": "delivery-health", "repository": "acme/checkout", **payload},
    )


def test_a_schedule_routes_to_dora_and_does_not_explain() -> None:
    classification = classify(_schedule())

    assert classification.domains == ("dora",)
    assert classification.certain is True
    assert classification.explains is False, (
        "a measurement ranked into root causes diagnoses an incident nobody claimed"
    )


def test_the_subject_carries_what_themis_reads() -> None:
    """`repository` and `window_days`, off `ctx.params`."""
    assert subject_of(_schedule(window_days=14)) == {
        "job": "delivery-health",
        "repository": "acme/checkout",
        "window_days": 14,
    }


def test_a_job_key_on_an_alert_does_not_route_to_themis() -> None:
    """Read from the kind, not only the payload. Alertmanager annotations are
    operator-supplied text and a `job` label is common in them."""
    alert = Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title="t",
        payload={"job": "delivery-health", "repository": "acme/checkout"},
    )

    assert scheduled_job_of(alert) is None
    assert "dora" not in classify(alert).domains


def test_every_scheduled_job_names_an_implemented_domain() -> None:
    """A job the planner cannot build a step for is a 202 that investigates nothing
    - the shape this repository keeps finding."""
    for job, domains in SCHEDULED_JOBS.items():
        for domain in domains:
            assert domain in planner.IMPLEMENTED, f"job {job!r} names domain {domain!r}"


def test_themis_is_dispatchable_now() -> None:
    """The point of the receiver. Registered, and named by a plan a trigger produces."""
    from core.orchestrator import dispatcher, register_implemented

    register_implemented()
    assert "themis" in dispatcher.AGENTS
    assert planner.IMPLEMENTED["dora"] == "themis"


# --- the tenant reaches the row ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_tenant_the_receiver_established_is_on_the_investigation() -> None:
    """The receiver passes it to the runner; this is whether the runner keeps it.

    A plant that dropped `tenant=` from the Investigation constructor survived
    every test above - the recorder saw the right tenant and the row was still
    filed under the default. The seam is here, and the assertion is on the row
    that `GET /investigations/{id}` will scope by.
    """
    from agents._base.base_agent import AgentContext, BaseAgent
    from core.contracts.finding import Finding
    from core.orchestrator import dispatcher
    from core.orchestrator.router import investigate
    from core.store.investigations import InMemoryInvestigationStore

    class _Quiet(BaseAgent):
        domain = "dora"

        async def investigate(self, ctx: AgentContext) -> list[Finding]:
            return []

    original = dict(dispatcher.AGENTS)
    dispatcher.AGENTS.clear()
    dispatcher.register("themis", _Quiet)
    try:
        store = InMemoryInvestigationStore()
        run = await investigate(_schedule(), store=store, bus=InMemoryEventBus(), tenant="globex")
    finally:
        dispatcher.AGENTS.clear()
        dispatcher.AGENTS.update(original)

    assert run.tenant == "globex"
    stored = await store.get(run.id)
    assert stored is not None and stored.tenant == "globex"
