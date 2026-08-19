"""The connector gate: real PromQL, real HTTP, real bus events.

`tests/unit/test_connectors.py` asserts the shape. This asserts it *works*: a
PromQL query through the MCP tool against the Prometheus the simulator has been
writing into, an Alertmanager payload over real HTTP producing a real bus event,
and the allowlist refusing what it should.

The simulator has to have run first, or there is nothing to query. That is a
real dependency and it is checked rather than assumed - a gate that passes
against an empty Prometheus is a gate that proves the query parsed, not that the
connector works.

Run with:  make test-connectors

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from agents._base.base_agent import AgentContext, AgentStatus, BaseAgent
from agents._base.testing import RecordingBus, a_context
from connectors.prometheus.tools import build_server as build_prometheus
from core.config import get_settings
from core.contracts.finding import Finding
from simulator.runner import ScenarioRunner
from tests.integration.conftest import requires

pytestmark = [pytest.mark.integration, requires("prometheus", "pushgateway", "api")]

SETTINGS = get_settings()
PROMETHEUS = SETTINGS.prometheus.base
API = f"http://localhost:{SETTINGS.api.port}"

#: A metric the simulator writes. If this is absent the stack is up but empty,
#: which is a different failure and worth a different message.
SIM_METRIC = "pantheon_pod_cpu_cores"

#: Wall seconds the fixture spends writing. At a 1s scrape and a 5s query step
#: that is ~12 points - enough to prove a series came back without turning this
#: into a second copy of the simulator gate.
WRITE_SECONDS = 60.0
QUERY_STEP = "5s"


@pytest.fixture(scope="module")
def simulator_data() -> tuple[datetime, datetime]:
    """Write to Prometheus, and report the window that was actually written.

    Returning the window matters. The first version of this queried a fixed
    five minutes and found two points, because the fixture had only written
    twenty-five seconds - a failure that looks like a broken connector and is
    really a test asking about a period that does not exist.
    """
    started = datetime.now(UTC)
    runner = ScenarioRunner(tick_seconds=60.0)
    runner.baseline(speed=600.0, simulated_seconds=600.0 * WRITE_SECONDS)
    return started, datetime.now(UTC)


# --- a real query, through the real tool -------------------------------------


async def test_a_promql_query_returns_simulator_data(
    simulator_data: tuple[datetime, datetime],
) -> None:
    """The whole point: the MCP tool talks to Prometheus and gets series back."""
    started, ended = simulator_data
    server = build_prometheus()
    result = await server.call(
        "prometheus.query_range",
        {
            "query": f'sum({SIM_METRIC}{{service="checkout"}})',
            "start": started.isoformat(),
            "end": ended.isoformat(),
            "step": QUERY_STEP,
        },
    )

    assert result["resultType"] == "matrix"
    assert result["result"], (
        f"Prometheus answered but holds no {SIM_METRIC}. The stack is up and "
        "empty, which proves the query parsed and nothing else - run the "
        "simulator first."
    )
    values = result["result"][0]["values"]
    assert len(values) > 5, (
        f"only {len(values)} samples over the {WRITE_SECONDS:.0f}s the fixture "
        f"actually wrote, at a {QUERY_STEP} step"
    )
    assert all(float(value) > 0 for _at, value in values), "cpu series contains zeros"


async def test_an_instant_query_and_a_series_lookup_both_work(
    simulator_data: tuple[datetime, datetime],
) -> None:
    """All three declared tools, not just the one Argus leans on."""
    server = build_prometheus()

    instant = await server.call("prometheus.query_instant", {"query": f"sum({SIM_METRIC})"})
    assert instant["resultType"] == "vector"
    assert instant["result"], "instant query found nothing"

    series = await server.call("prometheus.series", {"match": [SIM_METRIC]})
    assert series, "series lookup found nothing"
    assert any(entry.get("__name__") == SIM_METRIC for entry in series)


async def test_a_malformed_query_is_reported_not_swallowed() -> None:
    """A connector answering a broken query with `[]` teaches an agent all is well."""
    from connectors._base.python.base_server import ToolError

    server = build_prometheus()
    with pytest.raises(ToolError, match="prometheus"):
        await server.call(
            "prometheus.query_range",
            {
                "query": "sum(((((",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-01T00:05:00Z",
            },
        )


# --- the allowlist, against a live connector ---------------------------------


class _Probe(BaseAgent):
    """Argus's manifest, with whichever tool the test wants to try."""

    domain = "anomaly"

    def __init__(self, tool: str, bind: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool = tool
        self._bind = bind

    def bind_tools(self, tools: Any) -> None:
        if not self._bind:
            return
        server = build_prometheus()

        async def call(**kwargs: Any) -> Any:
            return await server.call(self._tool, kwargs)

        tools.register(self._tool, call)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        await ctx.tools.call(self._tool, query=f"sum({SIM_METRIC})")
        return []


async def test_an_undeclared_tool_raises_tool_not_declared(
    simulator_data: tuple[datetime, datetime],
) -> None:
    """Argus may not reach Loki, even with a Loki connector running."""
    agent = _Probe("loki.query_range", bind=False)
    outcome = await agent.run(a_context())

    assert outcome.status is AgentStatus.DEGRADED
    assert "ToolNotDeclared" in (outcome.degraded_reason or ""), outcome.degraded_reason


async def test_a_declared_tool_with_no_connector_raises_tool_not_bound(
    simulator_data: tuple[datetime, datetime],
) -> None:
    """The other failure: declared, permitted, and nothing is serving it.

    Distinguishable from the one above. They were the same exception once, and
    a guard against the allowlist passed while the allowlist check was removed.
    """
    agent = _Probe("prometheus.query_instant", bind=False)
    outcome = await agent.run(a_context())

    assert outcome.status is AgentStatus.DEGRADED
    assert "ToolNotBound" in (outcome.degraded_reason or ""), outcome.degraded_reason


async def test_a_declared_and_bound_tool_succeeds(
    simulator_data: tuple[datetime, datetime],
) -> None:
    """The control. The two failures above are only evidence if this passes."""
    agent = _Probe("prometheus.query_instant", bind=True)
    outcome = await agent.run(a_context())

    assert outcome.status is AgentStatus.COMPLETE, outcome.degraded_reason
    assert outcome.tool_calls == 1


# --- Alertmanager, over real HTTP --------------------------------------------

ALERTMANAGER_PAYLOAD: dict[str, Any] = {
    "version": "4",
    "groupKey": '{}:{alertname="CheckoutErrorRateHigh"}',
    "truncatedAlerts": 0,
    "status": "firing",
    "receiver": "pantheon",
    "groupLabels": {"alertname": "CheckoutErrorRateHigh"},
    "commonLabels": {
        "alertname": "CheckoutErrorRateHigh",
        "service": "checkout",
        "severity": "critical",
    },
    "commonAnnotations": {"summary": "checkout 5xx rate above baseline"},
    "externalURL": "http://alertmanager:9093",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "CheckoutErrorRateHigh",
                "service": "checkout",
                "severity": "critical",
            },
            "annotations": {"summary": "checkout 5xx rate above baseline"},
            "startsAt": "2026-08-18T12:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://prometheus:9090/graph",
            "fingerprint": "b7a1c2d3e4f50617",
        }
    ],
}


async def test_an_alertmanager_payload_over_real_http_is_accepted() -> None:
    """The real endpoint, the real payload shape, no simulator-specific route."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{API}/webhooks/alertmanager", json=ALERTMANAGER_PAYLOAD)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["alert_count"] == 1
    assert body["status"] == "firing"
    assert body["investigation_id"]


async def test_a_body_that_is_not_a_notification_is_rejected() -> None:
    """400, not 202. Accepting anything would make the endpoint a black hole."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{API}/webhooks/alertmanager", json={"nope": True})
    assert response.status_code == 400


async def test_the_receiver_puts_a_trigger_on_the_bus_with_the_payload_verbatim() -> None:
    """In-process, because the bus is not observable across the HTTP boundary.

    Asserted here rather than only over HTTP: what matters downstream is that
    the Trigger carries Alertmanager's body untouched, and the wire test above
    cannot see inside the running API.
    """
    from fastapi.testclient import TestClient

    from api.main import create_app

    app = create_app()
    bus = RecordingBus()
    app.state.event_bus = bus

    with TestClient(app) as client:
        response = client.post("/webhooks/alertmanager", json=ALERTMANAGER_PAYLOAD)
    assert response.status_code == 202

    received = bus.of_type("trigger_received")
    assert len(received) == 1
    trigger = received[0].trigger
    assert trigger.source == "alertmanager"
    assert "CheckoutErrorRateHigh" in trigger.title
    assert trigger.payload == ALERTMANAGER_PAYLOAD, (
        "the payload must be stored verbatim - Alertmanager's schema varies by "
        "version, and the fields discarded today are the ones an investigation "
        "turns out to need tomorrow"
    )
