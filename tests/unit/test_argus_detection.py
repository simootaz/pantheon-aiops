"""Argus's detection: what it emits, what it refuses, and what it never claims.

The live gate is `tests/integration/test_argus_detection_flow.py`, which runs
this against a real stack in both directions. These are the properties that do
not need one.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext, AgentDegraded
from agents.anomaly.agent import (
    SERIES,
    Argus,
    SeriesSpec,
    _confidence,
    _parse,
    _Reading,
    _sustained_run,
)
from agents.anomaly.calibration import SCALE_FLOORS, SUSTAIN_SAMPLES, THRESHOLDS
from core.contracts.evidence import BaselineEstimator, MetricWindowPayload
from core.contracts.finding import FindingKind
from core.contracts.investigation import Trigger, TriggerKind

#: Members per peer axis, so every metric gets a plausible group rather than
#: whichever one the test happened to care about. A metric handed the wrong
#: label returns nothing, refuses, and aborts the scan - which would make every
#: test here a test of the refusal path.
MEMBERS = {
    "pod": [f"pod-{i}" for i in range(12)],
    "node": ["node-a", "node-b", "node-c"],
    "service": ["checkout", "payments", "catalog", "search", "notifier"],
}
SAMPLES = 30


class _Tools:
    """A tool surface that answers each query with data shaped for its metric."""

    def __init__(
        self, overrides: dict[str, dict[str, list[float]]] | None = None, fail: bool = False
    ) -> None:
        self.overrides = overrides or {}
        self.fail = fail
        self.queries: list[str] = []

    async def call(self, name: str, /, **kwargs: Any) -> Any:
        assert name == "prometheus.query_range", name
        query = kwargs["query"]
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("prometheus is unreachable")
        metric = next(m for m, spec in SERIES.items() if spec.query == query)
        spec = SERIES[metric]
        values = self.overrides.get(metric) or {
            member: [100.0 + index * 0.01] * SAMPLES
            for index, member in enumerate(MEMBERS[spec.label])
        }
        return _range(values, spec.label)


def _context() -> AgentContext:
    end = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    return AgentContext(
        investigation_id=uuid4(),
        trigger=Trigger(kind=TriggerKind.SIMULATION, received_at=end, source="test"),
        window_start=end - timedelta(minutes=5),
        window_end=end,
    )


def _range(values: dict[str, list[float]], label: str = "pod") -> dict[str, Any]:
    """A Prometheus range payload with one series per member."""
    return {
        "result": [
            {
                "metric": {label: member},
                "values": [[float(1_700_000_000 + i), str(v)] for i, v in enumerate(series)],
            }
            for member, series in values.items()
        ]
    }


# --- the two tables must describe the same set -------------------------------


def test_every_calibrated_metric_can_be_fetched() -> None:
    """A threshold nothing knows how to query is a number that never runs."""
    missing = sorted(set(THRESHOLDS) - set(SERIES))
    assert not missing, (
        f"calibrated but unfetchable: {missing}. Argus iterates SERIES, so a metric "
        "with a threshold and no spec is silently never scanned - which looks exactly "
        "like a clean window."
    )


def test_every_fetchable_metric_is_calibrated_or_refuses() -> None:
    """A spec without calibration must produce a refusal, not a scan."""
    uncalibrated = sorted(set(SERIES) - set(THRESHOLDS))
    assert not uncalibrated or all(m not in SCALE_FLOORS for m in uncalibrated), (
        f"{uncalibrated} have a floor but no threshold, which is half a calibration"
    )


def test_every_spec_names_a_label_the_query_groups_by() -> None:
    """The peer axis has to be a label the query actually returns.

    Naming the wrong one does not error - it returns nothing for that key, the
    member set comes back empty, and the metric is silently never compared.
    """
    for metric, spec in SERIES.items():
        assert spec.label in {"pod", "node", "service"}, f"{metric}: {spec.label}"
        if spec.label == "service":
            assert "by (service)" in spec.query or "ci_pipeline" in spec.query, (
                f"{metric} compares services but its query does not group by one"
            )


# --- the sustained-run rule ---------------------------------------------------


def _readings(zs: list[float]) -> list[_Reading]:
    return [
        _Reading(at=float(i), value=1.0, z=z, centre=0.0, scale=1.0, floor_engaged=False)
        for i, z in enumerate(zs)
    ]


def test_a_single_crossing_is_not_an_incident() -> None:
    """One instant over the line is a scrape."""
    below = [1.0] * 10
    for position in range(len(below)):
        spiked = list(below)
        spiked[position] = 99.0
        assert _sustained_run(_readings(spiked), threshold=5.0) is None


def test_a_run_one_short_of_the_rule_is_refused() -> None:
    """The boundary, both sides of it.

    A rule that fires at `SUSTAIN_SAMPLES - 1` would be a different rule, and
    the difference is invisible in any output.
    """
    short = _readings([1.0] + [99.0] * (SUSTAIN_SAMPLES - 1) + [1.0])
    assert _sustained_run(short, threshold=5.0) is None

    exact = _readings([1.0] + [99.0] * SUSTAIN_SAMPLES + [1.0])
    run = _sustained_run(exact, threshold=5.0)
    assert run == (1, 1 + SUSTAIN_SAMPLES)


def test_a_negative_excursion_counts() -> None:
    """A pod far BELOW its peers is as anomalous as one far above.

    Memory that collapses, a service that stops serving errors because it stopped
    serving - the sign is not what makes it interesting.
    """
    assert _sustained_run(_readings([-99.0] * SUSTAIN_SAMPLES), threshold=5.0) is not None


# --- confidence claims no more than it has ------------------------------------


def test_confidence_is_a_fraction_of_the_window() -> None:
    assert _confidence(0, 100) == 0.0
    assert _confidence(50, 100) == 0.5
    assert _confidence(100, 100) == 1.0
    assert _confidence(5, 0) == 0.0


def test_confidence_has_no_resolution_finer_than_one_over_n() -> None:
    """Every value it can produce is a multiple of 1/n.

    Which is why `n` is carried on the Finding: 0.333 from three instants and
    0.333 from three thousand are different claims and the number cannot say so.
    """
    for usable in (3, 7, 137):
        for crossings in range(usable + 1):
            value = _confidence(crossings, usable)
            assert abs(value * usable - round(value * usable)) < 1e-9


# --- what a scan emits --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_window_emits_nothing() -> None:
    """Twelve identical peers cannot produce a peer-relative anomaly."""
    agent = Argus()
    ctx = _context()
    ctx.tools = _Tools()
    findings = await agent.investigate(ctx)
    assert [f for f in findings if f.kind is FindingKind.ANOMALY] == []


@pytest.mark.asyncio
async def test_a_moving_member_is_named_with_its_series_and_label() -> None:
    values = {member: [100.0 + i * 0.01] * SAMPLES for i, member in enumerate(MEMBERS["pod"])}
    values["pod-7"] = [100.07] * 10 + [900.0] * 20
    agent = Argus()
    ctx = _context()
    ctx.tools = _Tools({"memory": values, "cpu": values, "latency": values})

    anomalies = [f for f in await agent.investigate(ctx) if f.kind is FindingKind.ANOMALY]
    assert anomalies, "a member 800x its peers produced no Finding"

    for finding in anomalies:
        assert finding.subject is not None
        assert finding.subject.name == "pod-7", finding.subject
        assert finding.evidence, "an ANOMALY with no Evidence is inadmissible"
        payload = finding.evidence[0].payload
        assert isinstance(payload, MetricWindowPayload), type(payload)
        assert payload.estimator is BaselineEstimator.MEDIAN_MAD
        assert payload.deviation_sigma is not None and abs(payload.deviation_sigma) > 5
        assert payload.baseline_centre is not None
        assert payload.baseline_scale is not None
        assert finding.evidence[0].source.query, "Evidence must cite the query"
        assert any(t.startswith("n:") for t in finding.tags), "N must be on the Finding"
        assert finding.rationale is None, (
            "Argus states what it observed; explaining why is Delphi's job, and a "
            "templated sentence would read like an explanation nobody produced"
        )


@pytest.mark.asyncio
async def test_an_uncalibrated_metric_refuses_out_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not scanning must be visible. A silent skip looks like a clean window.

    The refusal goes out as `AgentDegraded`, not as a Finding this agent builds:
    the runtime owns DEGRADED so that every agent reports inability the same way,
    and `test_only_the_base_constructs_a_degraded_finding` fails the build for
    anyone who forgets. The anomalies found before the refusal ride along as
    `partial` rather than being thrown away.
    """
    monkeypatch.setitem(
        SERIES,
        "invented_this_afternoon",
        SeriesSpec(query="pantheon_nonsense", label="pod", unit="", resource_kind="pod"),
    )
    values = {member: [100.0 + i * 0.01] * SAMPLES for i, member in enumerate(MEMBERS["pod"])}
    values["pod-3"] = [100.03] * 10 + [900.0] * 20
    agent = Argus()
    ctx = _context()
    ctx.tools = _Tools({"memory": values, "cpu": values, "latency": values})

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert "invented_this_afternoon" in raised.value.reason, (
        f"the refusal does not name the metric: {raised.value.reason}"
    )
    assert "means nothing" in raised.value.reason, (
        "a partial scan must say that a quiet result for the unscanned metrics "
        f"proves nothing: {raised.value.reason}"
    )
    assert not raised.value.retryable, "an uncalibrated metric will not calibrate on a retry"
    assert raised.value.partial, (
        "anomalies found before the refusal were discarded; a partial scan keeps what it did see"
    )
    assert all(f.kind is FindingKind.ANOMALY for f in raised.value.partial)


@pytest.mark.asyncio
async def test_an_unreachable_prometheus_is_degraded_not_quiet() -> None:
    """Inability to look is not absence of anomalies."""
    agent = Argus()
    ctx = _context()
    ctx.tools = _Tools(fail=True)
    with pytest.raises(AgentDegraded, match="not an absence of anomalies"):
        await agent.investigate(ctx)


@pytest.mark.asyncio
async def test_a_floor_determined_reading_says_so() -> None:
    """A number the floor produced must not look like one the data produced.

    Three identical peers give a MAD of exactly zero, the floor takes over, and
    the resulting z is a property of the floor. That has to reach the Finding.
    """
    values = {
        "node-a": [0.34] * SAMPLES,
        "node-b": [0.34] * SAMPLES,
        "node-c": [0.34] * 20 + [0.9] * 10,
    }
    agent = Argus()
    ctx = _context()
    ctx.tools = _Tools({"disk_ratio": values})

    findings = await agent.investigate(ctx)
    anomalies = [f for f in findings if f.kind is FindingKind.ANOMALY]
    assert anomalies, "a node at 2.6x its peers produced no Finding"
    engaged = [f for f in anomalies if "floor-engaged" in f.tags]
    assert engaged, "the floor decided this reading and no Finding said so"
    for finding in engaged:
        payload = finding.evidence[0].payload
        assert isinstance(payload, MetricWindowPayload), type(payload)
        assert payload.scale_floor_engaged is True
        assert "FLOOR" in finding.evidence[0].summary.upper()


def test_parse_drops_non_finite_samples() -> None:
    """`0/0` in PromQL is NaN, and NaN through a median poisons everything after."""
    payload = {
        "result": [
            {"metric": {"pod": "a"}, "values": [[1.0, "1.0"], [2.0, "NaN"], [3.0, "3.0"]]},
        ]
    }
    parsed = _parse(payload, "pod")
    assert list(parsed["a"].values()) == [1.0, 3.0]
