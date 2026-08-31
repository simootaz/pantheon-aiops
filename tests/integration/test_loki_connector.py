"""The Loki connector against a real Loki, both directions.

The negative direction is the point, and it is not a hypothetical. Loki does not
answer an empty result the same way at every endpoint:

* the LABEL endpoints omit `data` entirely - the body is `{"status":"success"}`
  and no more, so `body["data"]` raises KeyError;
* `query_range` always sends `data`, with `resultType`, an empty `result` and a
  full `stats` block.

Both were measured here, against a running Loki. The first was found by accident
and initially generalised to both, which would have made the connector fabricate
`{"result": []}` for a query_range that had actually changed behaviour - a
fabrication indistinguishable from a service that genuinely logged nothing.

WHAT THIS ASSERTS THAT A UNIT TEST CANNOT
-------------------------------------------
Which of those two things Loki really does, at which endpoint. A unit test with
a hand-written body asserts the shape someone expected. The offline tests in
tests/unit/test_connectors.py encode what this gate measured, and this gate is
what keeps them honest when Loki is upgraded.

Run with:  make test-loki

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from connectors._base.python.base_server import ToolError
from connectors.loki import tools as loki
from connectors.loki.tools import build_server
from core.config import get_settings
from simulator.log_generator import LOKI_JOB_LABEL
from simulator.runner import ScenarioRunner
from simulator.scenario import load
from tests.integration.conftest import requires

pytestmark = [pytest.mark.integration, requires("loki", "pushgateway")]

SETTINGS = get_settings()

#: The scenario written into Loki for this gate. The assertions here are about
#: the connector's wire handling, not about log content - that is the simulator
#: gate's job - so it runs at the coarsest tick that still produces streams.
SCENARIO = "bad_deploy_5xx"

#: One hour of simulated time per tick, and a speed high enough that the runner
#: never sleeps. The scenario spans a simulated day, so this is ~24 ticks of two
#: HTTP round trips each rather than the 48 wall-minutes that `speed=30` asked
#: for on the first attempt.
TICK_SECONDS = 3600.0
SPEED = 1e9

#: What the simulator actually puts on a log stream. There is no `scenario`
#: label here - that one is on the metrics - and asking for it returned an empty
#: result that looked like a broken connector.
STREAM = f'{{job="{LOKI_JOB_LABEL}", service="checkout"}}'

#: A window long before anything was written. Loki answers `{"status":"success"}`
#: with NO `data` key at all - the case that produced the KeyError.
ANCIENT = "2020-01-01T00:00:00Z"


def _nanos(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1_000_000_000))


@pytest.fixture(scope="module")
def written() -> tuple[str, str]:
    """Write logs into Loki, and report the window actually written.

    The window is returned rather than assumed. Querying a fixed five minutes
    when the fixture wrote thirty seconds fails in a way that looks like a
    broken connector and is really a test asking about a period that never
    existed - the same mistake the Prometheus gate made once.
    """
    started = datetime.now(UTC)
    runner = ScenarioRunner(
        pushgateway=f"http://{SETTINGS.pushgateway.host_port}",
        loki_url=SETTINGS.loki.base,
        tick_seconds=TICK_SECONDS,
    )
    runner.run(load(SCENARIO), speed=SPEED, send_pipelines=False)
    finished = datetime.now(UTC)
    return _nanos(started - timedelta(minutes=1)), _nanos(finished + timedelta(minutes=1))


async def test_a_real_logql_query_returns_lines(written: tuple[str, str]) -> None:
    """The positive direction: a query through the connector reaches Loki."""
    start, end = written
    result = await loki.query_range({"query": STREAM, "start": start, "end": end, "limit": 50})

    streams = result.get("result", [])
    assert streams, (
        f"the run wrote {SCENARIO} logs but the connector read none back for "
        f"{STREAM}. "
        "Either the write failed or the query window is wrong."
    )
    assert result.get("resultType") == "streams", (
        f"Loki answered with resultType={result.get('resultType')!r}; a log query "
        "returns streams, and anything else means the query was rewritten somewhere"
    )
    assert any(entries for stream in streams if (entries := stream.get("values"))), (
        "streams came back with no entries in any of them"
    )


async def test_an_empty_query_range_window_is_silence_and_not_a_crash() -> None:
    """A log window that reads as an error rather than as silence is the
    difference between "the service said nothing" and "we could not ask".

    query_range sends `data` here - empty `result`, full `stats` - so this
    asserts pass-through rather than the label behaviour below. Getting those
    two the same way round is the whole reason this gate exists.
    """
    result = await loki.query_range(
        {"query": '{job="nothing-ever-had-this-label"}', "start": ANCIENT, "end": ANCIENT}
    )

    assert result["result"] == [], f"an empty window came back with entries: {result!r}"
    assert result["resultType"] == "streams", (
        "query_range no longer states a resultType on an empty window. The "
        "connector reports absence rather than inventing one, so this is a "
        "change in Loki worth knowing about."
    )


async def test_an_empty_label_window_omits_data_and_comes_back_empty() -> None:
    """The endpoint that really does omit `data`, asserted where it is true.

    This is the case that crashed the connector with a KeyError. Asserting it
    against a real Loki rather than a canned body is what tells us the offline
    tests encode Loki's behaviour and not our memory of it.
    """
    assert await loki.labels({"start": ANCIENT, "end": ANCIENT}) == []
    assert await loki.labels({"name": "service", "start": ANCIENT, "end": ANCIENT}) == []


async def test_labels_come_back_and_a_named_label_yields_its_values(
    written: tuple[str, str],
) -> None:
    """Both halves of the one declared tool.

    Names alone cannot build a LogQL selector, which is why `loki.labels` answers
    both questions rather than only the first.
    """
    start, end = written

    names = await loki.labels({"start": start, "end": end})
    assert "service" in names, f"the simulator writes a `service` label; Loki listed {names}"

    values = await loki.labels({"name": "service", "start": start, "end": end})
    assert "checkout" in values, f"`service` has values {values}, not including checkout"


async def test_the_delete_api_is_unreachable_through_this_connector() -> None:
    """Against a real Loki that does expose it.

    The allowlist is what makes this true; asserting it here rather than only
    offline is the difference between "our helper refuses" and "the endpoint
    cannot be reached from this process".
    """
    with pytest.raises(ToolError, match="deliberately unreachable"):
        await loki._get("/loki/api/v1/delete", {"query": '{job="x"}'}, empty=[])

    with pytest.raises(ToolError, match="deliberately unreachable"):
        await loki._get("/loki/api/v1/push", empty=[])


async def test_a_malformed_logql_query_is_reported_not_swallowed() -> None:
    """A rejected query must not look like an empty result.

    They are the same shape to a careless adapter - nothing came back either way
    - and confusing them means an agent concludes a service was silent when the
    truth is that nobody asked a valid question.
    """
    with pytest.raises(ToolError, match="loki returned 4"):
        await loki.query_range({"query": "this is not LogQL", "start": ANCIENT, "end": ANCIENT})


async def test_the_server_the_gate_exercises_is_the_one_the_process_serves() -> None:
    """The registry under test is the registry `server.py` builds.

    A gate that constructs its own tool table proves the table, not the server.
    """
    registry = build_server()
    assert set(registry.tools) == {"loki.query_range", "loki.labels"}
    assert registry.read_only

    result: Any = await registry.call(
        "loki.query_range",
        {"query": '{job="nothing-ever-had-this-label"}', "start": ANCIENT, "end": ANCIENT},
    )
    assert result["result"] == []
