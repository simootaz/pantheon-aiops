"""Moira: the fit, the refusals, and the predictions scored against the generator.

Three layers, each answering something the one above cannot:

- `fit()` on synthetic series, because the arithmetic has edge cases - a flat
  line, a falling line, two points - that a scenario never produces.
- `Moira.investigate()` against a fake Prometheus, because what the agent
  REFUSES is the part a scenario cannot show: a scenario has data, and the
  interesting failure is a window with none.
- The generator's own series, fitted directly, because the predictions in
  `docs/moira-predictions/01-disk-time-to-full.md` are about numbers and a
  number is measured, not asserted.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext, AgentDegraded
from agents._base.tool_binding import BoundTools
from agents.capacity import agent as moira_module
from agents.capacity.agent import HORIZON_HOURS, LOOKBACK_HOURS, Moira
from agents.capacity.forecast import MIN_SAMPLES, NotEnoughSamples, fit
from core.contracts.evidence import EvidenceKind, MetricSample
from core.contracts.finding import FindingKind
from core.contracts.investigation import Trigger, TriggerKind

T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _samples(values: list[float], *, step_hours: float = 1.0) -> list[MetricSample]:
    return [
        MetricSample(at=T0 + timedelta(hours=i * step_hours), value=value)
        for i, value in enumerate(values)
    ]


# --- the fit --------------------------------------------------------------------------


def test_a_straight_ramp_is_recovered_exactly() -> None:
    """Slope, intercept and R² on a line with no noise. The arithmetic itself."""
    forecast = fit(_samples([0.30, 0.31, 0.32, 0.33, 0.34]), limit=1.0)

    assert forecast.rate_per_hour == pytest.approx(0.01)
    assert forecast.r2 == pytest.approx(1.0)
    assert forecast.current == pytest.approx(0.34)
    assert forecast.time_to_limit_hours == pytest.approx((1.0 - 0.34) / 0.01)


def test_a_falling_series_never_reaches_the_limit() -> None:
    """A line going the other way never gets there. `None`, not a negative number
    and not infinity - "infinite" is not a number a contract can carry."""
    forecast = fit(_samples([0.50, 0.45, 0.40, 0.35]), limit=1.0)

    assert forecast.rate_per_hour < 0
    assert forecast.time_to_limit_hours is None
    assert not forecast.crossing_within(HORIZON_HOURS)


def test_a_flat_series_is_a_perfect_fit_that_goes_nowhere() -> None:
    """ss_tot is zero and the line explains it exactly. R² of 0 there would call
    a perfect fit a bad one; R² of 1 with no slope is the honest reading."""
    forecast = fit(_samples([0.40, 0.40, 0.40, 0.40]), limit=1.0)

    assert forecast.rate_per_hour == pytest.approx(0.0)
    assert forecast.r2 == pytest.approx(1.0)
    assert forecast.time_to_limit_hours is None


def test_noise_lowers_r2_without_changing_the_verdict() -> None:
    """The fit quality travels with the projection rather than suppressing it."""
    clean = fit(_samples([0.30, 0.32, 0.34, 0.36, 0.38, 0.40]), limit=1.0)
    # The same line with ±0.01 on four points, chosen zero-mean AND
    # uncorrelated with time (Σx·e = 0): least squares moves the slope by
    # Σx·e / Σx², so only a perturbation orthogonal to x leaves it alone. The
    # first version of this fixture was zero-mean and not orthogonal, and the
    # slope moved 6 % - which the test then blamed on the fit.
    noisy = fit(_samples([0.29, 0.33, 0.34, 0.36, 0.39, 0.39]), limit=1.0)

    assert noisy.r2 < clean.r2
    assert noisy.rate_per_hour == pytest.approx(clean.rate_per_hour)
    assert noisy.crossing_within(HORIZON_HOURS) and clean.crossing_within(HORIZON_HOURS)


def test_two_points_are_refused_rather_than_fitted_perfectly() -> None:
    """Two points always fit a line with R² = 1.0, which would report certainty
    about nothing."""
    with pytest.raises(NotEnoughSamples):
        fit(_samples([0.30, 0.40]), limit=1.0)
    assert MIN_SAMPLES == 3


def test_samples_at_one_instant_are_refused() -> None:
    """A slope over zero elapsed time is undefined, not zero."""
    same_time = [MetricSample(at=T0, value=v) for v in (0.3, 0.4, 0.5)]
    with pytest.raises(NotEnoughSamples, match="no time elapsed"):
        fit(same_time, limit=1.0)


def test_the_fit_is_order_independent() -> None:
    """Samples arrive in whatever order Prometheus returns them."""
    values = [0.30, 0.31, 0.32, 0.33, 0.34]
    forward = fit(_samples(values), limit=1.0)
    backward = fit(list(reversed(_samples(values))), limit=1.0)

    assert backward.rate_per_hour == pytest.approx(forward.rate_per_hour)
    assert backward.current == pytest.approx(forward.current)


def test_already_past_the_limit_and_rising_is_zero_hours_not_negative() -> None:
    forecast = fit(_samples([0.98, 0.99, 1.00, 1.01]), limit=1.0)

    assert forecast.time_to_limit_hours == 0.0
    assert forecast.crossing_within(HORIZON_HOURS)


def test_the_horizon_separates_filling_from_eventually_full() -> None:
    """Every disk fills eventually. Only one inside the horizon is a risk."""
    slow = fit(_samples([0.300, 0.301, 0.302, 0.303]), limit=1.0)  # ~700 h to full
    fast = fit(_samples([0.30, 0.40, 0.50, 0.60]), limit=1.0)  # ~4 h to full

    assert not slow.crossing_within(HORIZON_HOURS)
    assert fast.crossing_within(HORIZON_HOURS)


# --- the agent, offline -------------------------------------------------------------


def _range_response(label: str, series: dict[str, list[tuple[float, float]]]) -> dict[str, Any]:
    """The shape Prometheus returns for a range query."""
    return {
        "resultType": "matrix",
        "result": [
            {"metric": {label: member}, "values": [[at, str(value)] for at, value in points]}
            for member, points in series.items()
        ],
    }


class _Prometheus:
    """A fake `prometheus.query_range` answering from a table of series."""

    def __init__(self, answers: dict[str, dict[str, list[tuple[float, float]]]]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        query = kwargs["query"]
        if query not in self.answers:
            raise RuntimeError(f"unexpected query {query!r}")
        return _range_response("node", self.answers[query])


def _ctx(*, window_minutes: float = 5.0) -> AgentContext:
    end = T0
    return AgentContext(
        investigation_id=uuid4(),
        trigger=Trigger(
            kind=TriggerKind.ALERT, received_at=end, source="alertmanager", title="test"
        ),
        window_start=end - timedelta(minutes=window_minutes),
        window_end=end,
    )


def _bind(agent: Moira, fake: _Prometheus) -> Any:
    tools = BoundTools(
        declared=frozenset(agent.manifest.tools), max_calls=agent.manifest.budget.max_tool_calls
    )
    tools.register("prometheus.query_range", fake)
    return tools


def _filling(hours: float, *, start: float, end: float, total: float = 200e9) -> _Prometheus:
    """A node filling linearly from `start` to `end` of its disk over `hours`."""
    points = 60
    stamps = [
        T0.timestamp() - hours * 3600 + i * (hours * 3600 / (points - 1)) for i in range(points)
    ]
    used = [(at, total * (start + (end - start) * i / (points - 1))) for i, at in enumerate(stamps)]
    return _Prometheus(
        {
            "pantheon_node_disk_used_bytes": {"node-a": used},
            "pantheon_node_disk_total_bytes": {"node-a": [(at, total) for at in stamps]},
        }
    )


@pytest.mark.asyncio
async def test_a_filling_disk_is_a_risk_finding_with_the_projection_on_it() -> None:
    """The case: 0.4 → 0.8 over 20 h is 0.02/h, so 10 h to full."""
    agent = Moira()
    fake = _filling(20.0, start=0.4, end=0.8)
    ctx = _ctx()
    ctx.tools = _bind(agent, fake)

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    (finding,) = degraded.value.partial
    assert finding.kind is FindingKind.RISK
    assert finding.subject is not None and finding.subject.name == "node-a"
    (evidence,) = finding.evidence
    assert evidence.kind is EvidenceKind.CAPACITY_FORECAST
    payload = evidence.payload
    assert payload.kind == "capacity_forecast"
    assert payload.rate_per_hour == pytest.approx(0.02, rel=0.01)
    assert payload.time_to_limit_hours == pytest.approx(10.0, rel=0.02)
    assert payload.limit == 1.0
    assert "full" in finding.title


@pytest.mark.asyncio
async def test_memory_is_refused_on_every_run_and_says_why() -> None:
    """Prediction 5. Every run is partial for memory, because nothing tells Moira
    the limit - and a run that reported itself whole would be claiming to have
    looked."""
    agent = Moira()
    ctx = _ctx()
    ctx.tools = _bind(agent, _filling(20.0, start=0.4, end=0.8))

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    assert "memory" in str(degraded.value)
    assert "no limit metric" in str(degraded.value)
    assert degraded.value.retryable is False, "a missing metric does not appear on retry"


@pytest.mark.asyncio
async def test_a_disk_that_fills_after_the_horizon_is_a_clean_window() -> None:
    """Prediction 4's mechanism. 0.30 → 0.31 over 20 h is ~1 400 h to full: the
    generator's accumulation term, and in a real cluster the fact that disks
    fill eventually. Not a Finding."""
    agent = Moira()
    ctx = _ctx()
    ctx.tools = _bind(agent, _filling(20.0, start=0.30, end=0.31))

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    assert degraded.value.partial == []


@pytest.mark.asyncio
async def test_prometheus_unreachable_is_a_retryable_refusal_not_a_clean_window() -> None:
    class _Down:
        async def __call__(self, **kwargs: Any) -> Any:
            raise ConnectionError("prometheus:9090 refused")

    agent = Moira()
    ctx = _ctx()
    tools = BoundTools(
        declared=frozenset(agent.manifest.tools), max_calls=agent.manifest.budget.max_tool_calls
    )
    tools.register("prometheus.query_range", _Down())
    ctx.tools = tools

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    assert degraded.value.retryable is True
    assert "inability to look" in str(degraded.value)


@pytest.mark.asyncio
async def test_moira_reads_its_own_window_and_puts_it_on_the_finding() -> None:
    """Five minutes of a three-day fill is noise with a slope through it. Moira
    asks for LOOKBACK_HOURS and the Finding says what was read."""
    agent = Moira()
    fake = _filling(20.0, start=0.4, end=0.8)
    ctx = _ctx(window_minutes=5.0)
    ctx.tools = _bind(agent, fake)

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    asked = fake.calls[0]
    assert asked["end"] == ctx.window_end.timestamp()
    assert asked["start"] == pytest.approx(
        (ctx.window_end - timedelta(hours=LOOKBACK_HOURS)).timestamp()
    )
    (finding,) = degraded.value.partial
    assert finding.window_start == ctx.window_end - timedelta(hours=LOOKBACK_HOURS), (
        "the Finding claims the incident window for a fit over a day"
    )


@pytest.mark.asyncio
async def test_a_window_longer_than_the_lookback_is_not_shortened() -> None:
    """A caller that asked for more history than the lookback gets what it asked."""
    agent = Moira()
    fake = _filling(20.0, start=0.4, end=0.8)
    ctx = _ctx(window_minutes=48 * 60)
    ctx.tools = _bind(agent, fake)

    with pytest.raises(AgentDegraded):
        await agent.investigate(ctx)

    assert fake.calls[0]["start"] == ctx.window_start.timestamp()


@pytest.mark.asyncio
async def test_a_node_reporting_only_one_side_of_the_ratio_is_skipped() -> None:
    """A ratio built from a stale or missing total is a ratio against the wrong disk."""
    agent = Moira()
    fake = _filling(20.0, start=0.4, end=0.8)
    fake.answers["pantheon_node_disk_total_bytes"] = {}  # used reports, total does not
    ctx = _ctx()
    ctx.tools = _bind(agent, fake)

    with pytest.raises(AgentDegraded) as degraded:
        await agent.investigate(ctx)

    assert degraded.value.partial == []


def test_every_resource_moira_projects_declares_a_limit_source() -> None:
    """`RESOURCES` is what Moira can answer; `UNLIMITED` is what it cannot and
    why. A metric in neither is one nobody decided about."""
    assert set(moira_module.RESOURCES) == {"disk"}
    assert "memory" in moira_module.UNLIMITED
    assert not set(moira_module.RESOURCES) & set(moira_module.UNLIMITED)


# --- the predictions, scored against the generator ----------------------------------
#
# The generator is deterministic. Sampling node-a's disk through it at the cadence
# Moira uses and fitting the result is the measurement the predictions were
# written for - the integration gate does the same through Prometheus, divided by
# the compression factor.


def _generator_series(
    scenario: str, *, ending_at_progress: float, hours: float
) -> list[MetricSample]:
    """node-a's disk ratio from the generator, over `hours` ending at a point on the
    first phase - the window Moira would read if the incident ended there."""
    from simulator.cluster import NODES
    from simulator.metrics_generator import MetricsGenerator
    from simulator.scenario import load

    sc = load(scenario)
    # No gateway: nothing is pushed, the generator is only asked for values. The
    # default reads configuration, which is where an endpoint belongs.
    gen = MetricsGenerator()
    node_a = next(node for node in NODES if node.name == "node-a")
    phase = sc.phases[0]
    end = sc.baseline_seconds + phase.start_seconds + ending_at_progress * phase.duration_seconds
    start = end - hours * 3600
    step = moira_module.STEP_SECONDS * 10  # a coarser cadence keeps this under a second
    samples: list[MetricSample] = []
    t = start
    while t <= end:
        used = gen._node_disk(node_a, t, sc.active_at(t))
        samples.append(
            MetricSample(at=datetime.fromtimestamp(t, tz=UTC), value=used / node_a.disk_bytes)
        )
        t += step
    return samples


def test_prediction_1_and_2_the_fill_rate_and_its_fit() -> None:
    """P1: 0.0092 ± 0.001 per hour. P2: R² above 0.99. Both over the whole fill.

    Measured 0.00903 and 0.9990: both hit.
    """
    whole_fill = _generator_series("disk_pressure", ending_at_progress=0.9, hours=54.0)
    forecast = fit(whole_fill, limit=1.0)

    assert forecast.rate_per_hour == pytest.approx(0.0092, abs=0.001), f"P1: {forecast}"
    assert forecast.r2 > 0.99, f"P2: R²={forecast.r2}"


def test_prediction_3_time_to_full_over_moiras_own_window() -> None:
    """P3: 42 h from the midpoint and 18.5 h from 90 %, within ten percent.

    Measured over Moira's 24-hour window: 44.9 h (hit, 6 % off) and 20.5 h
    (MISS, 11 % off). The prediction was computed from two instantaneous samples,
    and the generator's 1 % seasonal term - which it applies to disk even though
    disk has no rhythm of its own - tilts any window shorter than a cycle. Named
    in advance under "what would make me wrong"; scored as a miss in the
    prediction record. The assertions below hold the MEASURED values so a change
    to the fit or the generator is visible, and say which prediction each was.
    """
    from_mid = fit(
        _generator_series("disk_pressure", ending_at_progress=0.5, hours=LOOKBACK_HOURS),
        limit=1.0,
    )
    from_90 = fit(
        _generator_series("disk_pressure", ending_at_progress=0.9, hours=LOOKBACK_HOURS),
        limit=1.0,
    )

    assert from_mid.time_to_limit_hours == pytest.approx(42.4, rel=0.10), f"P3a: {from_mid}"
    # Not 18.5. The miss is the record; a tolerance widened until the prediction
    # passed would be a prediction fitted to its answer.
    assert from_90.time_to_limit_hours == pytest.approx(20.5, rel=0.03), f"P3b: {from_90}"
    assert from_mid.crossing_within(HORIZON_HOURS) and from_90.crossing_within(HORIZON_HOURS)


def test_prediction_4_memory_leak_leaves_disk_alone() -> None:
    """P4: the only disk movement on `memory_leak` is the accumulation term, and
    it is years from full. A capacity Finding here would report the generator."""
    forecast = fit(
        _generator_series("memory_leak", ending_at_progress=1.0, hours=LOOKBACK_HOURS), limit=1.0
    )

    assert not forecast.crossing_within(HORIZON_HOURS), f"P4: {forecast}"


# --- tool binding -------------------------------------------------------------------


def test_bind_tools_attaches_exactly_what_the_manifest_declares() -> None:
    """The runtime builds the toolset from the manifest and hands it to
    `bind_tools`; this is the only place an implementation survives that."""
    from agents.capacity.tools import IMPLEMENTATIONS

    agent = Moira()
    tools = BoundTools(
        declared=frozenset(agent.manifest.tools), max_calls=agent.manifest.budget.max_tool_calls
    )
    agent.bind_tools(tools)

    assert set(IMPLEMENTATIONS) == set(agent.manifest.tools) == {"prometheus.query_range"}
    assert set(tools._implementations) == set(IMPLEMENTATIONS)


def test_attach_cannot_widen_the_allowlist() -> None:
    """A toolset declaring nothing gets nothing, however much this module
    implements. Registration fills the allowlist; it never extends it."""
    from agents.capacity.tools import attach

    empty = BoundTools(declared=frozenset(), max_calls=1)
    attach(empty)

    assert empty._implementations == {}
