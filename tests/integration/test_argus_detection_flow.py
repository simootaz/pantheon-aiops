"""Argus against the live stack, in both directions.

A detector is only as good as its negative case. A rule that fires on
everything passes every positive test and is worse than no rule, so the
baseline case runs **three times** - once is one sample of a distribution, and
every calibration record on this branch exists because a single run was
mistaken for a bound.

WHAT IS ASSERTED, AND WHAT DELIBERATELY IS NOT
----------------------------------------------
Asserted: a clean baseline produces **no** ANOMALY Findings, and each scenario
produces at least one naming the series that actually moved.

Not asserted: that a scenario produces *only* Findings about its own metric.
It does not, and it should not. `latency` reads 23.85 during `bad_deploy_5xx`
and `cpu` reads 8.93 during `noisy_neighbor`, and both are true - a bad deploy
does raise latency. Requiring one Finding per incident would be requiring a
diagnosis, which is the thing Argus explicitly does not do.

Run with:  make test-argus

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext
from agents._base.tool_binding import BoundTools
from agents.anomaly.agent import SERIES, Argus
from connectors.prometheus import tools as prometheus_tools
from core.contracts.evidence import MetricWindowPayload
from core.contracts.finding import Finding, FindingKind
from core.contracts.investigation import Trigger, TriggerKind
from simulator.alerting import GATE_TICK_SECONDS
from simulator.metrics_generator import MetricsGenerator
from simulator.runner import ScenarioRunner
from simulator.scenario import load

pytestmark = pytest.mark.integration

SPEED = 630.0
#: Baseline runs are shorter than the calibration runs because this gate is
#: asking a yes/no question, not deriving a bound. Three of them is what makes
#: the negative case a claim rather than an anecdote.
BASELINE_WALL = 300.0
BASELINE_REPEATS = 3
SETTLE_SECONDS = 20.0

#: The metric each scenario is expected to move. Argus will name others too -
#: see the module docstring - and this is the one that must appear.
EXPECTED = {
    "bad_deploy_5xx": "error_ratio",
    "flaky_test_storm": "ci_ratio",
    "memory_leak": "memory",
    "noisy_neighbor": "latency",
    "disk_pressure": "disk_ratio",
}


def _tools() -> BoundTools:
    """Argus's real toolset, bound to the real Prometheus connector."""
    bound = BoundTools(
        declared=frozenset(
            {"prometheus.query_range", "prometheus.query_instant", "prometheus.series"}
        ),
        max_calls=len(SERIES) * 2,
    )
    bound.register(
        "prometheus.query_range",
        lambda **kwargs: prometheus_tools.query_range(
            {
                "query": kwargs["query"],
                "start": kwargs["start"],
                "end": kwargs["end"],
                "step": kwargs.get("step", "1s"),
            }
        ),
    )
    return bound


async def _scan(started: float, ended: float) -> list[Finding]:
    ctx = AgentContext(
        investigation_id=uuid4(),
        trigger=Trigger(
            kind=TriggerKind.SIMULATION, received_at=datetime.now(tz=UTC), source="gate"
        ),
        window_start=datetime.fromtimestamp(started, tz=UTC),
        window_end=datetime.fromtimestamp(ended, tz=UTC),
    )
    ctx.tools = _tools()
    return await Argus().investigate(ctx)


def _describe(findings: list[Finding]) -> str:
    return (
        ", ".join(
            f"{f.title} (conf {f.confidence:.3f}, {[t for t in f.tags if t.startswith('n:')]})"
            for f in findings
        )
        or "none"
    )


@pytest.mark.parametrize("attempt", range(BASELINE_REPEATS))
@pytest.mark.asyncio
async def test_a_clean_baseline_produces_no_anomalies(attempt: int, stack: None) -> None:
    """The negative case, three times.

    Every threshold in the matrix was derived as the smallest value with zero
    exceedances over held-out runs. This asserts the end-to-end consequence of
    that: the agent, the connector, the parser, the sustain rule and the
    thresholds together produce silence on a clean cluster.
    """
    MetricsGenerator().reset()
    time.sleep(SETTLE_SECONDS)
    started = time.time()
    report = ScenarioRunner(tick_seconds=GATE_TICK_SECONDS, wall_paced=True).baseline(
        speed=SPEED, simulated_seconds=SPEED * BASELINE_WALL
    )
    ended = time.time()
    assert not report.degraded, f"the baseline run itself was degraded: attempt {attempt}"

    findings = await _scan(started, ended)
    anomalies = [f for f in findings if f.kind is FindingKind.ANOMALY]
    refusals = [f for f in findings if f.kind is FindingKind.DEGRADED]

    assert not refusals, (
        f"a metric refused to scan on a clean run, so this attempt proves nothing "
        f"about the others: {_describe(refusals)}"
    )
    assert not anomalies, (
        f"attempt {attempt}: a clean baseline produced {len(anomalies)} anomalies. "
        f"{_describe(anomalies)}"
    )


@pytest.mark.parametrize("scenario", sorted(EXPECTED))
@pytest.mark.asyncio
async def test_each_scenario_is_detected_on_the_series_that_moved(
    scenario: str, stack: None
) -> None:
    """The positive case: a Finding naming the metric the fault actually touched.

    The window handed to Argus is the fault window the runner reports, not the
    whole run. Scanning the whole run would let a baseline-length quiet period
    dilute the crossing fraction, and the confidence would then describe the
    run rather than the fault.
    """
    expected_metric = EXPECTED[scenario]
    MetricsGenerator().reset()
    time.sleep(SETTLE_SECONDS)
    started = time.time()
    report = ScenarioRunner(tick_seconds=GATE_TICK_SECONDS, wall_paced=True).run(
        load(scenario), speed=SPEED, send_pipelines=False
    )
    ended = time.time()
    assert not report.degraded, f"{scenario}: the run itself was degraded"
    assert report.fault_started_wall is not None, f"{scenario}: no fault window was recorded"

    fault_from = started + report.fault_started_wall
    fault_to = started + (report.fault_ended_wall or (ended - started))
    findings = await _scan(fault_from, fault_to)
    anomalies = [f for f in findings if f.kind is FindingKind.ANOMALY]

    named = [f for f in anomalies if f"metric:{expected_metric}" in f.tags]
    assert named, (
        f"{scenario} moved {expected_metric} and Argus did not report it. "
        f"Findings: {_describe(anomalies)}"
    )

    for finding in named:
        assert finding.evidence, "an ANOMALY must cite Evidence"
        evidence = finding.evidence[0]
        assert evidence.subject is not None and evidence.subject.name, (
            "the Evidence must name the member that moved, not just the metric"
        )
        payload = evidence.payload
        assert isinstance(payload, MetricWindowPayload), type(payload)
        assert payload.deviation_sigma is not None, "deviation_sigma must be populated"
        assert payload.estimator.value == "median_mad", (
            f"the estimator must be named, got {payload.estimator}"
        )
        assert payload.samples, "Evidence with no samples cannot be checked by a human"
        assert any(t.startswith("n:") for t in finding.tags), (
            "N must be on the Finding: the confidence has no resolution finer than 1/N"
        )
        # Not an assertion about the value - a floor-determined reading is
        # legitimate, it just has to be distinguishable from a measured one.
        assert isinstance(payload.scale_floor_engaged, bool)
