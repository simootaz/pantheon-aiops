"""The simulator's gate: assertions about the DATA, not the code shape.

A simulator emitting flat lines would pass every structural test in this
repository and be worthless. So this runs the real generators against a real
Prometheus and a real Loki, reads the series back out, and asserts statistical
properties of what arrived.

METHODS AND THRESHOLDS, STATED
------------------------------
*Variance* — coefficient of variation (stdev / mean) must exceed 0.02. A
constant series has CV 0; anything below 2% is flat for practical purposes.

*Seasonality* — autocorrelation of the mean-centred series. ACF at a lag of one
simulated day must exceed 0.35, and must exceed ACF at half a day by at least
0.25. Requiring both matters: a slow monotonic drift produces high autocorrelation
at *every* lag, so the peak-versus-trough comparison is what distinguishes a
cycle from a ramp.

*Separability* — z-score of the fault window against the baseline distribution,
(mean_fault - mean_baseline) / stdev_baseline, must be at least 3.0, and Cohen's
d at least 1.5. The z-score alone can be inflated by a tiny baseline stdev, so
the effect size is checked too.

*Timing* — onset is the first sample exceeding baseline mean + 3 stdev and
sustained for three consecutive samples. It must fall within a tolerance of where
the scenario says the phase starts.

SPEED
-----
Assertions are made at compressed speed. Real time is exercised separately and
asserts variance and liveness only — **seasonality cannot be asserted in real
time**, because one cycle is 24 hours and a pushgateway cannot backfill. That is
the same limitation ROADMAP tracks against `remote_write`, and it is stated here
rather than quietly skipped.

Run with:  make test-sim

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import httpx
import numpy as np
import pytest

from core.config import get_settings
from simulator.cluster import PODS_BY_NAME
from simulator.runner import KEEP_UP_THRESHOLD as KEEP_UP_FRACTION
from simulator.runner import RunReport, ScenarioRunner
from simulator.scenario import load
from tests.integration.conftest import requires

# Read through core.config like everything else, so the gate cannot end up
# pointed at a different Prometheus than the code it is testing.
_settings = get_settings()
PROMETHEUS = _settings.prometheus.base
LOKI = _settings.loki.base
PUSHGATEWAY = _settings.pushgateway.host_port

pytestmark = [pytest.mark.integration, requires("prometheus", "loki", "pushgateway")]

# --- constants derived from two measured limits, not guessed ----------------
#
# 1. Prometheus scrapes the pushgateway once a second, in WALL time. So the
#    samples available per simulated day is 86400/speed, and no compression can
#    buy more of them.
# 2. A tick costs a fixed amount of wall clock whatever span it covers, because
#    the cost is two HTTP round trips rather than the payload — measured at
#    ~102ms here and stable over hundreds of ticks. So the fastest honest speed
#    is tick_seconds/cost, and asking for more makes the runner fall behind —
#    which it reports (RunReport.kept_up) instead of hiding.
#
# The cost is measured per machine by the `tick_cost` fixture rather than
# written down here, so nothing below encodes the speed of one laptop.

#: 30 Prometheus samples per simulated day.
BASELINE_SPEED = 2880.0
#: Five simulated days: enough to see the cycle repeat rather than infer it from
#: one period, which is not evidence of a period at all.
BASELINE_WALL_SECONDS = 150.0

#: bad_deploy_5xx is 97800 simulated seconds, of which the fault occupies 11400.
#: At 240x that is a 408s run with a 48s fault window — enough samples for both
#: statistics below. Faster compression shrinks the fault window until n is too
#: small to claim anything from it.
SCENARIO_SPEED = 240.0

#: Ticks are sized from a measured cost (see the `tick_cost` fixture), with this
#: much headroom, so a run keeps up on a slow machine as well as a fast one.
#: Generous on purpose: calibration runs against a fresh stack, and both
#: Prometheus and Loki get slower as they accumulate data over a long run.
TICK_HEADROOM = 2.5
#: Never go below this, or a phase boundary lands further from where the
#: scenario puts it than the timing tolerance allows.
MIN_TICK = 60.0
CALIBRATION_TICKS = 12

CV_FLOOR = 0.02
ACF_FLOOR = 0.35
ACF_MARGIN = 0.25
Z_FLOOR = 3.0
COHENS_D_FLOOR = 1.5


@dataclass(frozen=True)
class Series:
    """A Prometheus range query result, as arrays."""

    timestamps: np.ndarray
    values: np.ndarray

    def __len__(self) -> int:
        return len(self.values)


def reset_pushgateway() -> None:
    """Drop the previous run's group before pushing a new one.

    Without this, the second run's counters start again from zero while the
    gateway is still serving the first run's totals. Prometheus reads that as a
    counter reset and `rate()` reports a phantom spike exactly at the boundary —
    which is where a fault-onset test is looking.
    """
    httpx.delete(f"http://{PUSHGATEWAY}/metrics/job/pantheon_sim", timeout=10.0)


def query_range(query: str, *, start: float, end: float, step: str = "1s") -> Series:
    """Read a series back out of the real Prometheus, over an explicit window."""
    response = httpx.get(
        f"{PROMETHEUS}/api/v1/query_range",
        params={"query": query, "start": f"{start:.3f}", "end": f"{end:.3f}", "step": step},
        timeout=30.0,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    if not result:
        return Series(np.array([]), np.array([]))
    pairs = result[0]["values"]
    return Series(
        timestamps=np.array([float(point[0]) for point in pairs]),
        values=np.array([float(point[1]) for point in pairs]),
    )


def measured(label: str, value: str, against: str) -> None:
    """Print what was measured, not only what failed.

    A gate that reports a bare "passed" hides whether it cleared its threshold
    comfortably or by a hair, and a threshold nobody watches drifts into being
    decorative. `make test-sim` passes `-s` so these always reach the log.
    """
    print(f"    measured  {label:<34} {value:>12}   (threshold: {against})")


# --- statistics -------------------------------------------------------------


def coefficient_of_variation(values: np.ndarray) -> float:
    mean = float(np.mean(values))
    return float(np.std(values) / mean) if mean else 0.0


def autocorrelation(values: np.ndarray, lag: int) -> float:
    """Pearson autocorrelation at `lag`, on the mean-centred series."""
    if lag <= 0 or lag >= len(values):
        return 0.0
    centred = values - np.mean(values)
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(centred[:-lag], centred[lag:]) / denominator)


def z_score(fault: np.ndarray, baseline: np.ndarray) -> float:
    spread = float(np.std(baseline))
    if spread == 0.0:
        return math.inf
    return float((np.mean(fault) - np.mean(baseline)) / spread)


def cohens_d(fault: np.ndarray, baseline: np.ndarray) -> float:
    pooled = math.sqrt((float(np.var(fault)) + float(np.var(baseline))) / 2.0)
    if pooled == 0.0:
        return math.inf
    return float((np.mean(fault) - np.mean(baseline)) / pooled)


def onset_index(values: np.ndarray, baseline: np.ndarray, sustain: int = 3) -> int | None:
    """First index exceeding baseline mean + 3 stdev for `sustain` samples.

    The sustain requirement is what stops a single noisy sample from being
    reported as the onset of an incident.
    """
    threshold = float(np.mean(baseline) + 3.0 * np.std(baseline))
    run = 0
    for index, value in enumerate(values):
        run = run + 1 if value > threshold else 0
        if run >= sustain:
            return index - sustain + 1
    return None


# --- the runs, each shared by the assertions that read it -------------------


@dataclass(frozen=True)
class Run:
    """One simulator execution and the window it occupied."""

    report: RunReport
    started: float
    ended: float

    def series(self, query: str, step: str = "1s") -> Series:
        return query_range(query, start=self.started, end=self.ended, step=step)

    def wall_for(self, simulated_seconds: float) -> float:
        """Where a point in simulated time actually landed on the wall clock.

        Every wall-clock claim in this file goes through here, and it divides by
        the speed the run **achieved** rather than the speed it was asked for.

        This is not a detail. The first run of this gate asked for 300x, got
        196x, and three assertions failed in ways that pointed at the data:
        Cohen's d came out at 0.81 because the window computed as "the fault"
        was still 70% baseline, and onset appeared to be 152s early. The
        generator was correct throughout. Only the arithmetic converting
        simulated time to wall time was wrong.
        """
        return simulated_seconds / self.report.achieved_speed

    @property
    def samples_per_simulated_day(self) -> float:
        """How many 1s Prometheus samples one simulated day received."""
        return self.wall_for(86_400.0)


@pytest.fixture(scope="module")
def tick_cost() -> float:
    """What one tick costs on *this* machine, in wall seconds.

    A tick is two HTTP round trips whatever span of simulated time it covers, so
    its cost is a property of the machine and its Docker networking rather than
    of the simulator. Every speed below is only achievable when
    `tick_seconds / speed` exceeds that cost.

    Measuring it beats hard-coding it. A constant tuned on the machine this was
    written on would make the gate pass here and flake on a CI runner — and the
    failure would present as a seasonality problem rather than a timing one,
    which is the worst kind of misleading test.
    """
    reset_pushgateway()
    runner = ScenarioRunner(pushgateway=PUSHGATEWAY, loki_url=LOKI, tick_seconds=300.0)
    # An enormous speed asks for no sleeping at all, so the run goes as fast as
    # the pushes allow and the elapsed wall time IS the cost.
    report = runner.baseline(speed=1e9, simulated_seconds=300.0 * CALIBRATION_TICKS)
    cost = report.wall_seconds / report.ticks
    assert 0.0 < cost < 5.0, f"implausible tick cost {cost:.3f}s; the stack may be unhealthy"
    return cost


def tick_for(speed: float, cost: float) -> float:
    """The smallest whole minute of simulated time that `speed` can sustain."""
    return max(MIN_TICK, math.ceil(speed * cost * TICK_HEADROOM / 60.0) * 60.0)


@pytest.fixture(scope="module")
def baseline_run(tick_cost: float) -> Run:
    """Emit only normal behaviour, for long enough to see several days."""
    reset_pushgateway()
    runner = ScenarioRunner(
        pushgateway=PUSHGATEWAY,
        loki_url=LOKI,
        tick_seconds=tick_for(BASELINE_SPEED, tick_cost),
    )
    started = time.time()
    report = runner.baseline(
        speed=BASELINE_SPEED, simulated_seconds=BASELINE_WALL_SECONDS * BASELINE_SPEED
    )
    return Run(report=report, started=started, ended=time.time())


@pytest.fixture(scope="module")
def scenario_run(tick_cost: float) -> Run:
    """Run bad_deploy_5xx end to end against the live stack."""
    reset_pushgateway()
    runner = ScenarioRunner(
        pushgateway=PUSHGATEWAY,
        loki_url=LOKI,
        tick_seconds=tick_for(SCENARIO_SPEED, tick_cost),
    )
    started = time.time()
    report = runner.run(load("bad_deploy_5xx"), speed=SCENARIO_SPEED, send_pipelines=False)
    return Run(report=report, started=started, ended=time.time())


# --- the run delivered the compression it claimed ----------------------------


@pytest.mark.parametrize("fixture_name", ["baseline_run", "scenario_run"])
def test_the_run_delivered_the_speed_it_was_asked_for(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """`--speed N` is a promise, and this is the test that it was kept.

    The other assertions in this file no longer depend on it — they convert
    simulated time to wall time through `Run.wall_for`, which divides by the
    speed actually achieved. That is deliberate: those tests are about the data,
    and should not fail because the machine was busy.

    This one is about the parameter. A run that quietly delivers 200x when asked
    for 2880x still produces correct data in simulated time, so nothing else here
    would notice — which is exactly why it needs its own assertion.
    """
    run: Run = request.getfixturevalue(fixture_name)
    report = run.report
    measured(
        f"{fixture_name} speed",
        f"{report.achieved_speed:.0f}x",
        f">= {report.speed * KEEP_UP_FRACTION:.0f}x ({report.speed:.0f}x asked)",
    )
    assert report.kept_up, (
        f"{fixture_name} asked for {report.speed:.0f}x and delivered "
        f"{report.achieved_speed:.0f}x over {report.ticks} ticks. Pushing costs "
        f"wall time; raise tick_seconds or lower the speed."
    )


# --- the baseline is not a flat line ----------------------------------------


def test_baseline_variance_is_non_zero(baseline_run: Run) -> None:
    """A constant series makes every downstream anomaly detector worthless."""
    series = baseline_run.series('sum(pantheon_pod_cpu_cores{service="checkout"})')
    assert len(series) > 60, (
        f"only {len(series)} samples came back; Prometheus is not scraping the "
        "pushgateway often enough for any statistical claim to mean anything"
    )

    cv = coefficient_of_variation(series.values)
    measured("baseline CV (checkout cpu)", f"{cv:.4f}", f"> {CV_FLOOR}")
    assert cv > CV_FLOOR, (
        f"coefficient of variation is {cv:.4f}, at or below the {CV_FLOOR} floor — "
        "the baseline is flat for practical purposes"
    )


def test_baseline_seasonality_is_statistically_detectable(baseline_run: Run) -> None:
    """Assert the periodicity; do not eyeball a graph.

    Both conditions are required. A monotonic drift autocorrelates highly at
    every lag, so a high ACF at one day proves nothing on its own — the peak has
    to stand above the half-day trough for the series to be a cycle rather than
    a ramp.
    """
    series = baseline_run.series("sum(pantheon_http_request_duration_seconds)")
    values = series.values
    samples_per_day = round(baseline_run.samples_per_simulated_day)

    assert samples_per_day >= 10, "too few samples per simulated day to test a period"
    assert len(values) >= samples_per_day * 3, (
        f"{len(values)} samples covers under three simulated days; a period cannot be "
        "confirmed from a single cycle"
    )

    at_period = autocorrelation(values, samples_per_day)
    at_half = autocorrelation(values, samples_per_day // 2)
    measured("samples per simulated day", f"{samples_per_day}", ">= 10")
    measured("ACF at one simulated day", f"{at_period:.3f}", f"> {ACF_FLOOR}")
    measured("ACF(day) - ACF(half day)", f"{at_period - at_half:.3f}", f"> {ACF_MARGIN}")

    assert at_period > ACF_FLOOR, (
        f"autocorrelation at a lag of one simulated day is {at_period:.3f}, below "
        f"{ACF_FLOOR} — there is no daily cycle in this series"
    )
    assert at_period - at_half > ACF_MARGIN, (
        f"ACF(day)={at_period:.3f} barely exceeds ACF(half-day)={at_half:.3f}; a margin "
        f"under {ACF_MARGIN} is the signature of a drift or trend, not a cycle"
    )


# --- the fault is separable, and it lands where the scenario says ------------


def _error_rate(run: Run) -> Series:
    return run.series(
        'sum(rate(pantheon_http_requests_total{service="checkout",status="500"}[20s]))'
    )


#: rate() cannot report a step change sooner than its own window after the step,
#: and needs a full window of counter history before it means anything at all.
RATE_WINDOW = 20.0


def _fault_onset_wall(run: Run) -> float:
    """Where the scenario's error phase lands on the wall clock, for this run."""
    scenario = load("bad_deploy_5xx")
    spike = next(phase for phase in scenario.phases if phase.name == "errors_spike")
    return run.wall_for(scenario.baseline_seconds + spike.start_seconds)


def _split_at_fault(run: Run, series: Series) -> tuple[np.ndarray, np.ndarray]:
    """Baseline and fault windows, split at the scenario's own phase boundary.

    Splitting on a fixed fraction of the series would bake the answer into the
    test. This splits where the scenario says the fault starts, so the windows
    are defined by the scenario rather than chosen to pass.
    """
    boundary = run.started + _fault_onset_wall(run)
    warmup = series.timestamps > run.started + RATE_WINDOW + 10.0
    baseline = series.values[warmup & (series.timestamps < boundary)]
    fault = series.values[series.timestamps >= boundary + RATE_WINDOW]
    return baseline, fault


def test_injected_fault_is_separable_from_baseline(scenario_run: Run) -> None:
    """z-score against the baseline distribution, plus an effect size.

    Both are asserted because either alone can mislead: a z-score is inflated by
    a small baseline spread, and Cohen's d says nothing about how far outside
    normal variation a single observation falls.
    """
    series = _error_rate(scenario_run)
    baseline, fault = _split_at_fault(scenario_run, series)

    assert len(baseline) > 60, f"baseline window has only {len(baseline)} samples"
    assert len(fault) > 15, f"fault window has only {len(fault)} samples"

    z = z_score(fault, baseline)
    d = cohens_d(fault, baseline)
    measured("windows (baseline / fault)", f"{len(baseline)} / {len(fault)}", "> 60 / > 15")
    measured("fault z-score", f"{z:.1f}", f">= {Z_FLOOR}")
    measured("fault Cohen's d", f"{d:.1f}", f">= {COHENS_D_FLOOR}")

    assert z >= Z_FLOOR, (
        f"the fault window sits {z:.2f} standard deviations from baseline, below the "
        f"{Z_FLOOR} floor — it is not distinguishable from normal variation "
        f"(baseline mean {np.mean(baseline):.4f}, fault mean {np.mean(fault):.4f})"
    )
    assert d >= COHENS_D_FLOOR, (
        f"Cohen's d is {d:.2f}, below {COHENS_D_FLOOR}; the z-score is being carried by "
        "a small baseline spread rather than by a real effect"
    )


def test_fault_onset_matches_the_scenario_definition(scenario_run: Run) -> None:
    """Onset must land where the scenario says it does, within tolerance."""
    expected_wall = _fault_onset_wall(scenario_run)
    series = _error_rate(scenario_run)
    baseline, _ = _split_at_fault(scenario_run, series)

    # Search only the part of the series where rate() is meaningful. Scanning
    # from index 0 finds the warm-up transient and reports onset at t=0 — which
    # is what the first run of this gate did.
    warm = series.timestamps > scenario_run.started + RATE_WINDOW + 10.0
    values, stamps = series.values[warm], series.timestamps[warm]

    index = onset_index(values, baseline)
    assert index is not None, (
        "the error rate never crossed baseline mean + 3 stdev; the fault was injected "
        "but never became visible in Prometheus"
    )

    observed_wall = float(stamps[index] - scenario_run.started)
    measured(
        "fault onset (observed/expected)",
        f"{observed_wall:.0f}s/{expected_wall:.0f}s",
        f"within {RATE_WINDOW + 5.0 + expected_wall * 0.10:.0f}s",
    )
    # The rate window, a scrape interval, and 10% of the elapsed run — each lag
    # named, rather than one number chosen because it passed.
    tolerance = RATE_WINDOW + 5.0 + expected_wall * 0.10

    assert abs(observed_wall - expected_wall) <= tolerance, (
        f"fault onset observed {observed_wall:.0f}s into the run; the scenario places it "
        f"at {expected_wall:.0f}s (tolerance {tolerance:.0f}s)"
    )


def test_fault_duration_matches_the_scenario_definition(scenario_run: Run) -> None:
    """The fault must also *stop*, and stop roughly when the scenario says.

    A deviation that never clears is indistinguishable from a permanent
    regression, and would teach a remediation agent that nothing it does helps.
    """
    scenario = load("bad_deploy_5xx")
    expected = max(phase.end_seconds for phase in scenario.phases) - min(
        phase.start_seconds for phase in scenario.phases
    )
    report = scenario_run.report

    assert report.fault_started_wall is not None, "no phase was ever entered"
    assert set(report.phases_entered) == {
        "deploy_lands",
        "errors_spike",
        "pool_exhaustion",
    }, f"phases entered were {report.phases_entered}"

    observed = report.wall_seconds - report.fault_started_wall
    expected_wall = scenario_run.wall_for(expected)
    measured(
        "fault duration (observed/expected)",
        f"{observed:.0f}s/{expected_wall:.0f}s",
        f"within {expected_wall * 0.15 + 5.0:.0f}s",
    )
    assert abs(observed - expected_wall) <= expected_wall * 0.15 + 5.0, (
        f"the fault occupied {observed:.0f}s of wall clock; the scenario defines "
        f"{expected:.0f} simulated seconds, which is {expected_wall:.0f}s at the "
        f"{report.achieved_speed:.0f}x this run delivered"
    )


# --- metrics and logs describe the same cluster ------------------------------


def test_logs_reach_loki_for_the_pods_the_metrics_describe(scenario_run: Run) -> None:
    """A log stream naming pods the metrics never mention teaches false correlations."""
    response = httpx.get(
        f"{LOKI}/loki/api/v1/query_range",
        params={
            "query": '{job="pantheon-sim", service="checkout"}',
            "limit": "500",
            "start": f"{int(scenario_run.started * 1e9)}",
            "end": f"{int(scenario_run.ended * 1e9)}",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    streams = response.json()["data"]["result"]
    assert streams, "the run produced checkout log lines, but none reached Loki"

    seen = {stream["stream"]["pod"] for stream in streams}
    unknown = seen - set(PODS_BY_NAME)
    assert not unknown, f"logs mention pods the cluster does not define: {sorted(unknown)}"

    lines = [entry[1] for stream in streams for entry in stream["values"]]
    assert any("connection pool" in line.lower() for line in lines), (
        "the scenario injects pool_warning and pool_exhausted lines, but none are in Loki"
    )


# --- real time ----------------------------------------------------------------


def test_realtime_produces_live_varying_data() -> None:
    """Real time is available, and the data still varies.

    Seasonality is deliberately NOT asserted here, and that is not an oversight.
    One cycle is 24 hours of wall clock at speed 1, and a pushgateway discards
    timestamps so nothing can backfill the rest — no test that terminates can
    observe a daily period in real time. That is a transport limitation, the
    same one ROADMAP tracks against `remote_write`, not a property of the
    generator: the compressed run above exercises the identical code path and
    does assert the period.

    What can be asserted in real time is that the series is live and varying,
    and that is what this checks.
    """
    reset_pushgateway()
    runner = ScenarioRunner(pushgateway=PUSHGATEWAY, loki_url=LOKI, tick_seconds=3.0)
    started = time.time()
    runner.baseline(speed=1.0, simulated_seconds=45.0)
    ended = time.time()

    assert ended - started >= 40.0, (
        f"a real-time run of 45 simulated seconds took {ended - started:.1f}s of wall "
        "clock; speed 1 is not actually real time"
    )

    series = query_range(
        'sum(pantheon_pod_cpu_cores{service="checkout"})', start=started, end=ended
    )
    assert len(series) > 20, f"the real-time run produced only {len(series)} samples"

    cv = coefficient_of_variation(series.values)
    measured("real-time CV", f"{cv:.4f}", "> 0.005")
    measured("real-time elapsed", f"{ended - started:.1f}s", ">= 40s / 45 simulated")
    assert cv > 0.005, "the real-time series is not varying at all"
