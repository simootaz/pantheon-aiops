"""Structural guards over the simulator, runnable without a live stack.

`tests/integration/test_simulator_data.py` asserts on the data that reaches a
real Prometheus and a real Loki, and it is the gate that matters. These are the
cheap checks that run on every commit: the ones that catch a scenario naming a
pod that does not exist, or a metric whose baseline silently became a flat line.

The division is deliberate. A guard here should fail in milliseconds and without
Docker; anything that needs to observe real data belongs in the integration file.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import numpy as np
import pytest

from core.contracts.root_cause import RootCauseCategory
from simulator.cluster import NODES_BY_NAME, PODS, PODS_BY_NAME, pods_for
from simulator.log_generator import TEMPLATES, LogGenerator
from simulator.metrics_generator import (
    NOISE,
    SEASONAL_AMPLITUDE,
    MetricsGenerator,
    diurnal,
    weekly,
)
from simulator.runner import ScenarioRunner
from simulator.scenario import MetricName, Scenario, load_all

SCENARIOS = load_all()


# --- the tables that decide whether a series is flat ------------------------


def test_every_metric_has_a_noise_and_a_seasonal_amplitude() -> None:
    """A metric missing from either table is a crash or a flat line.

    Both tables are looked up with `[]` rather than `.get(metric, 0.0)`, so a
    gap is loud at runtime. This makes it loud at commit time instead.
    """
    metrics = set(MetricName)
    missing_noise = sorted(m.value for m in metrics - set(NOISE))
    assert not missing_noise, f"NOISE has no entry for {missing_noise}"
    assert set(SEASONAL_AMPLITUDE) == metrics, (
        f"SEASONAL_AMPLITUDE is missing "
        f"{sorted(m.value for m in metrics - set(SEASONAL_AMPLITUDE))}"
    )


def test_every_metric_samples_for_every_pod() -> None:
    """The whole cross-product, because a KeyError here kills a run mid-flight.

    A missing entry in the `base` table inside `_baseline` raises only when that
    particular metric is first sampled — which, for restarts, is the first push
    of the first run. Cheap to check exhaustively, so check exhaustively.
    """
    generator = MetricsGenerator()
    for pod in PODS:
        for metric in MetricName:
            value = generator.sample(pod, metric, 43_200.0, [])
            assert value >= 0.0, f"{pod.name}/{metric.value} sampled negative: {value}"


# --- the baseline actually moves --------------------------------------------


def test_the_daily_curve_has_a_real_peak_and_trough() -> None:
    """Assert the shape numerically rather than trusting the formula reads well."""
    values = [diurnal(hour / 24.0) for hour in range(24)]
    assert max(values) > 0.9, f"the daily curve never reaches its peak: max {max(values):.3f}"
    assert min(values) < -0.6, f"the daily curve never reaches a trough: min {min(values):.3f}"
    # Peak in the afternoon, trough overnight - not merely "it varies".
    assert 11 <= values.index(max(values)) <= 17, "the daily peak is not in the afternoon"
    assert values.index(min(values)) <= 5 or values.index(min(values)) >= 22, (
        "the daily trough is not overnight"
    )


def test_weekends_are_quieter_than_weekdays() -> None:
    """Without a weekly cycle a detector that learns 24h explains everything."""
    weekday = weekly(2 * 86_400.0)
    weekend = weekly(6 * 86_400.0)
    assert weekend < weekday, f"weekend multiplier {weekend} is not below weekday {weekday}"


@pytest.mark.parametrize("metric", [MetricName.REQUEST_RATE, MetricName.CPU, MetricName.LATENCY])
def test_a_day_of_baseline_is_not_a_flat_line(metric: MetricName) -> None:
    """The point of the whole simulator, checked without needing Prometheus.

    An anomaly detector trained on a constant is worthless, so this asserts the
    spread directly on the generator's own output.
    """
    generator = MetricsGenerator()
    pod = PODS_BY_NAME["checkout-7d4f9b-a1"]
    samples = np.array(
        [generator.sample(pod, metric, second, []) for second in range(0, 86_400, 300)]
    )
    cv = float(np.std(samples) / np.mean(samples))
    assert cv > 0.05, f"{metric.value} varies by only {cv:.4f} over a day; that is flat"

    midday = np.mean(samples[(12 * 12) : (16 * 12)])
    overnight = np.mean(samples[(1 * 12) : (5 * 12)])
    assert midday > overnight * 1.2, (
        f"{metric.value} midday mean {midday:.3f} is not meaningfully above the "
        f"overnight mean {overnight:.3f} — there is no daily cycle"
    )


# --- log sampling must not flatten what metrics kept -------------------------


@pytest.mark.parametrize("tick", [60.0, 300.0, 1200.0])
def test_log_sampling_preserves_the_daily_shape(tick: float) -> None:
    """Uniform sampling, not a per-pod ceiling.

    Clipping each pod at N lines per tick is the obvious way to bound log volume
    and it silently destroys the signal: at any tick long enough to matter, every
    pod saturates the ceiling and the log stream carries neither the daily cycle
    nor the difference between a busy service and a quiet one.
    """
    generator = LogGenerator()
    pod = PODS_BY_NAME["checkout-7d4f9b-a1"]
    peak = len(generator.baseline_lines(pod, 14 * 3600, tick))
    trough = len(generator.baseline_lines(pod, 3 * 3600, tick))
    assert peak > trough * 1.5, (
        f"at tick={tick:.0f}s the busiest hour produced {peak} lines and the quietest "
        f"{trough}; the sampling has flattened the daily cycle"
    )


@pytest.mark.parametrize("tick", [60.0, 300.0, 1200.0])
def test_log_sampling_preserves_the_gap_between_services(tick: float) -> None:
    """A busy service must still out-log a quiet one after sampling."""
    generator = LogGenerator()
    busy = len(generator.baseline_lines(PODS_BY_NAME["checkout-7d4f9b-a1"], 14 * 3600, tick))
    quiet = len(generator.baseline_lines(PODS_BY_NAME["notifier-4e7a1f-a1"], 14 * 3600, tick))
    assert busy > quiet * 1.5, (
        f"at tick={tick:.0f}s checkout produced {busy} lines and notifier {quiet}; "
        "sampling has erased the difference between a busy and a quiet service"
    )


# --- scenarios refer to things that exist ------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_every_phase_targets_something_that_exists(scenario: Scenario) -> None:
    """A typo in `target` would inject a fault into an empty set and report success."""
    for phase in scenario.phases:
        matched = pods_for(phase.target)
        assert matched, f"{scenario.name}/{phase.name} targets {phase.target!r}, matching no pods"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_every_log_pattern_names_a_template_that_exists(scenario: Scenario) -> None:
    """`render` raises on an unknown template, mid-run, on the tick that uses it."""
    for phase in scenario.phases:
        for pattern in phase.logs:
            assert pattern.template in TEMPLATES, (
                f"{scenario.name}/{phase.name} logs template {pattern.template!r}, "
                f"which is not one of {sorted(TEMPLATES)}"
            )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_restarts_are_perturbed_by_offset_never_by_factor(scenario: Scenario) -> None:
    """Restarts baseline at zero, so a multiplicative deviation does nothing.

    This is the kind of mistake that produces a scenario which runs cleanly,
    reports every phase, and injects no fault at all.
    """
    for phase in scenario.phases:
        for deviation in phase.deviations:
            if deviation.metric is MetricName.RESTARTS:
                assert deviation.offset is not None, (
                    f"{scenario.name}/{phase.name} scales restarts by a factor. The "
                    "restart baseline is 0, so this injects nothing — use `offset`."
                )


def test_the_five_scenarios_cover_five_distinct_root_causes() -> None:
    """Five scenarios that all mean `bad_deployment` would not test triage."""
    categories = [scenario.expected_root_cause.category for scenario in SCENARIOS]
    assert len(SCENARIOS) == 5, f"expected five scenarios, found {len(SCENARIOS)}"
    assert len(set(categories)) == 5, f"the scenarios collapse to {sorted(set(categories))}"
    for category in categories:
        assert category in set(RootCauseCategory), f"{category} is outside the contract vocabulary"


# --- the topology resolver refuses to guess ----------------------------------


def test_pods_for_rejects_a_target_it_does_not_recognise() -> None:
    """Matching nothing quietly is the failure mode worth preventing."""
    with pytest.raises(KeyError):
        pods_for("chekout")  # codespell:ignore


def test_pods_for_resolves_services_nodes_pods_and_wildcard() -> None:
    """The four accepted forms, so the guard above is not passing by accident."""
    assert len(pods_for("*")) == len(PODS)
    assert {pod.service for pod in pods_for("checkout")} == {"checkout"}
    assert {pod.node for pod in pods_for("node-c")} == {"node-c"}
    assert len(pods_for("search-2f6b8c-a1")) == 1


def test_every_pod_sits_on_a_node_that_exists() -> None:
    """Metrics label pods with their node; a dangling node breaks every by-node query."""
    for pod in PODS:
        assert pod.node in NODES_BY_NAME, f"{pod.name} is on unknown node {pod.node!r}"


# --- pacing ------------------------------------------------------------------


def test_the_run_loop_honours_speed_across_many_ticks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--speed N` is a promise, and many short ticks are where it gets broken.

    `time.sleep` may overshoot and can never undershoot, and the OS timer
    granularity is around 16ms on Windows. A loop that waits `tick / speed` on
    each iteration therefore loses a little every tick and never gets it back:
    over 554 ticks that turned a requested 2880x into a delivered 1880x, while
    the real work per tick was a steady 102ms with room to spare. The run was
    not too slow, it was sleeping too long, 554 times.

    The invariant belongs to the **run loop**, not to `_sleep_until`: the bug was
    passing a duration where a deadline was needed, and a deadline-taking helper
    self-corrects however it is written inside. So this drives `run()` and only
    stubs the I/O — 42 ticks of 20ms is where accumulated overshoot shows up.
    """
    runner = ScenarioRunner(tick_seconds=1.0)
    monkeypatch.setattr(runner.metrics, "push", lambda *a, **k: None)
    monkeypatch.setattr(runner.logs, "baseline_lines", lambda *a, **k: [])
    monkeypatch.setattr(runner.logs, "phase_lines", lambda *a, **k: [])
    monkeypatch.setattr(runner.logs, "push", lambda *a, **k: 0)

    report = runner.baseline(speed=50.0, simulated_seconds=40.0)

    assert report.ticks > 30, f"only {report.ticks} ticks; too few to detect drift"
    assert report.achieved_speed <= 60.0, (
        f"delivered {report.achieved_speed:.0f}x against 50x requested — the loop is "
        "not waiting at all, so speed is being ignored rather than honoured"
    )
    assert report.kept_up, (
        f"delivered {report.achieved_speed:.1f}x against 50x requested over "
        f"{report.ticks} ticks with no I/O at all. Nothing here is slow; the loop is "
        "sleeping per tick instead of pacing to a schedule, so every overshoot adds up."
    )
