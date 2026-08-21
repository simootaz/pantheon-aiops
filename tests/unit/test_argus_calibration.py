"""Guards over Argus's calibration: a bound must say what it was computed over.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import pytest

from agents.anomaly.calibration import (
    MEASURED_COVERAGE,
    SUSTAIN_SAMPLES,
    THRESHOLDS,
    WINDOW_SECONDS,
    BaselineRun,
    DegradationUnknownError,
    DetectionCoverage,
    InsufficientPeersError,
    MetricNotCalibratedError,
    NonFiniteSampleError,
    PartialPeerCoverageError,
    RunStatus,
    aggregate,
    peer_z,
    robust_z,
    threshold_for,
)


def _run(
    index: int, degraded: bool | None, worst: float, status: RunStatus = RunStatus.COMPLETE
) -> BaselineRun:
    return BaselineRun(index=index, status=status, degraded=degraded, max_abs_z={"latency": worst})


def test_an_aggregate_refuses_runs_whose_condition_is_unknown() -> None:
    """The rule: no aggregate from run records without degradation status.

    A false-positive bound over ten runs of which three had no logs is still
    usable. A bound that does not say which three is not, because nobody
    downstream can tell whether they are reading the system or an artefact of a
    broken sink - and the number looks identical either way.

    Same shape as `Verdict` requiring plan steps: a result that cannot be read
    without knowing what actually ran should not be constructible.
    """
    with pytest.raises(DegradationUnknownError, match="no degradation status"):
        aggregate([_run(1, False, 3.0), _run(2, None, 9.0)])

    # Stated, and it aggregates - including when the answer is "yes, degraded".
    bound = aggregate([_run(1, False, 3.0), _run(2, True, 9.0)])
    assert bound.runs_total == 2
    assert bound.runs_degraded == 1


def test_an_aggregate_refuses_runs_that_did_not_finish() -> None:
    """A partial run measured part of a baseline; its maximum is not comparable."""
    with pytest.raises(DegradationUnknownError, match="not COMPLETE"):
        aggregate([_run(1, False, 3.0), _run(2, False, 9.0, RunStatus.IN_PROGRESS)])
    with pytest.raises(DegradationUnknownError, match="not COMPLETE"):
        aggregate([_run(1, False, 3.0, RunStatus.FAILED)])


def test_the_bound_is_reported_across_all_runs_and_the_clean_subset() -> None:
    """Both numbers, because their difference is itself a finding.

    If dropping the degraded runs moves the bound, that says how much a broken
    log sink perturbs the metric baseline - worth knowing before Argus ships on
    the number, and invisible if only one figure is reported.
    """
    bound = aggregate([_run(1, False, 3.0), _run(2, False, 3.4), _run(3, True, 11.0)])

    assert bound.highest_abs_z_all == pytest.approx(11.0)
    assert bound.highest_abs_z_clean == pytest.approx(3.4)
    assert bound.materially_different, "an 11.0 against 3.4 is not a rounding difference"

    tight = aggregate([_run(1, False, 4.0), _run(2, True, 4.1)])
    assert not tight.materially_different


def test_every_scenario_declares_what_this_method_sees_of_it() -> None:
    """The onset-then-blind property is declared, not discovered at runtime.

    A trailing-window estimator goes blind to a fault that outlasts its window -
    the centre walks up to meet it. `disk_pressure` measured a peak z of 700
    against a tail of 1.4. That is a property of the method, and no window
    length hides it, so it is stated where the constants are.
    """
    from simulator.scenario import load_all

    scenarios = {scenario.name for scenario in load_all()}
    assert set(MEASURED_COVERAGE) == scenarios, (
        "a scenario exists with no measured coverage. Run the sweep against the "
        f"live stack and record it: {scenarios ^ set(MEASURED_COVERAGE)}"
    )
    assert DetectionCoverage.ONSET_ONLY in MEASURED_COVERAGE.values(), (
        "no scenario is marked onset-only. Either the sweep was re-run and the "
        "limitation genuinely went away, or this table was copied without measuring."
    )


def test_the_window_and_sustain_are_compatible() -> None:
    """k must fit inside the shortest elevated stretch any scenario produces.

    `noisy_neighbor` holds 14 samples above z=5. A sustain requirement near or
    above that detects nothing there, however well it works elsewhere.
    """
    shortest_measured_stretch = 14
    assert shortest_measured_stretch > SUSTAIN_SAMPLES, (
        f"SUSTAIN_SAMPLES={SUSTAIN_SAMPLES} does not fit inside the "
        f"{shortest_measured_stretch}-sample stretch noisy_neighbor produces"
    )
    assert shortest_measured_stretch < WINDOW_SECONDS, (
        "the window is shorter than the fault it must judge against"
    )


def test_a_flat_series_does_not_divide_by_zero() -> None:
    """`restarts` is exactly zero through a clean baseline, so MAD is zero."""
    flat = [0.0] * 120
    zs = robust_z(flat, window=90, scale_floor=1e-9)
    assert all(z == 0.0 for z in zs), "a flat series produced a non-zero deviation"

    spike = [0.0] * 120 + [1.0]
    assert robust_z(spike, window=90, scale_floor=1e-9)[-1] > 0, (
        "a departure from a flat baseline must still register"
    )


def test_the_window_looks_only_backwards() -> None:
    """A centred window lets an anomaly pull the baseline it is judged against."""
    values = [1.0] * 100 + [50.0] + [1.0] * 20
    zs = robust_z(values, window=90, scale_floor=0.01)
    assert zs[100] > 100, "the spike did not register against its own past"
    assert zs[99] == pytest.approx(0.0, abs=1.0), (
        "the sample before the spike moved, so the window is seeing the future"
    )


def test_a_metric_with_no_measured_bound_cannot_be_scanned() -> None:
    """A missing threshold is a refusal, never a fallback.

    A global default would let a metric added tomorrow inherit a number nobody
    measured for it - and the number would look exactly as authoritative as a
    measured one. Same shape as `BaselineRun.degraded` being `bool | None` with
    no default: the absent case has to be loud.

    `error_ratio` is the live example. Ten dedicated runs bounded it at 2.63;
    the sweep's clean pre-fault windows reached 15.67 on the same metric. Two
    samples from an unmapped space are not a bound, so it has no entry and
    Argus must refuse to scan it.
    """
    with pytest.raises(MetricNotCalibratedError, match="no measured baseline bound"):
        threshold_for("error_ratio")
    with pytest.raises(MetricNotCalibratedError, match="no measured baseline bound"):
        threshold_for("a_metric_invented_this_afternoon")


def test_every_declared_threshold_carries_the_measurement_behind_it() -> None:
    """A threshold whose basis is not attached cannot be re-derived.

    The first question asked of a threshold that misfired is what it was set
    from, and "someone chose 6" is not an answer this repository accepts.
    """
    for metric, entry in THRESHOLDS.items():
        assert entry.observed_baseline_max >= 0.0, metric
        assert entry.threshold > entry.observed_baseline_max, (
            f"{metric}: threshold {entry.threshold} does not clear its observed "
            f"baseline maximum {entry.observed_baseline_max}"
        )
        assert entry.runs >= 2, (
            f"{metric}: a bound from {entry.runs} run(s) is a sample, not a bound"
        )
        assert entry.conditions.strip(), (
            f"{metric}: no conditions recorded. A tight distribution over a narrow "
            "condition is not a bound over a wide one"
        )
        assert entry.margin > 1.0, metric


def test_a_nan_reaching_a_z_computation_raises() -> None:
    """NaN propagates through median and MAD without complaint.

    `0/0` in PromQL yields NaN. `statistics.median` of a list containing one
    returns NaN, the scale becomes NaN, and every comparison against it is
    False - so nothing fires and nothing errors. In the first peer-relative run
    every `error_ratio` baseline was NaN and it reached a results table looking
    like ordinary output, with plausible fault numbers beside it.

    A number that looks like a measurement and is not, which is the class this
    whole document is about. It must be loud.
    """
    for bad in (float("nan"), float("inf"), float("-inf")):
        values = [1.0] * 100 + [bad] + [1.0] * 20
        with pytest.raises(NonFiniteSampleError, match="non-finite"):
            robust_z(values, window=90, scale_floor=0.01)

    # The index is reported, because "somewhere in 121 samples" is not actionable.
    values = [1.0] * 50 + [float("nan")] + [1.0] * 70
    with pytest.raises(NonFiniteSampleError, match=r"index \[50\]"):
        robust_z(values, window=90, scale_floor=0.01)

    # Finite input still works.
    assert robust_z([1.0] * 100 + [9.0], window=90, scale_floor=0.01)[-1] > 0


# --- peer-relative preconditions --------------------------------------------

_TWELVE = [f"pod-{i}" for i in range(12)]


def _flat(peers: list[str], **overrides: float) -> dict[str, float]:
    samples = dict.fromkeys(peers, 1.0)
    samples.update(overrides)
    return samples


def test_a_peer_group_below_the_minimum_is_refused() -> None:
    """Small groups do not give a worse estimate - they give a degenerate one.

    With three peers MAD is the median of three deviations and is exactly zero
    whenever two agree, so the scale falls to its floor and z becomes a property
    of the floor. Measured on clean live data, 100% of sampled three-peer
    subsets exceeded |z| = 8, worst case 9444 - while the *best* subset came in
    at 24.92, which is why sampling one group proves nothing about the size.

    `disk_ratio` at three nodes produced 1599.63 on a clean baseline in one
    scenario and 1585.74 as a "signal" in another: the same degeneracy wearing
    opposite labels, and in production the first is a silent false positive.
    """
    for size in (2, 3, 5, 8, 11):
        peers = _TWELVE[:size]
        with pytest.raises(InsufficientPeersError, match="below the measured minimum"):
            peer_z(peers, _flat(peers))

    result = peer_z(_TWELVE, _flat(_TWELVE, **{"pod-0": 9.0}))
    assert result["pod-0"] > 0, "a full group must still produce a comparison"


def test_a_timestamp_missing_any_peer_is_refused() -> None:
    """Comparing whoever arrived is a different, smaller comparison.

    Not a filter someone may relax: dropping absent peers silently reduces the
    group, which lands in the degenerate regime above, and nothing in the output
    would say so. The numbers look ordinary.
    """
    samples = _flat(_TWELVE)
    del samples["pod-7"]
    with pytest.raises(PartialPeerCoverageError, match="did not report"):
        peer_z(_TWELVE, samples)

    samples = _flat(_TWELVE)
    for gone in ("pod-1", "pod-2", "pod-3"):
        del samples[gone]
    with pytest.raises(PartialPeerCoverageError, match="3 of 12"):
        peer_z(_TWELVE, samples)


def test_a_non_finite_peer_sample_is_refused() -> None:
    """Same rule as the temporal path: nan must be loud, not propagated."""
    with pytest.raises(NonFiniteSampleError):
        peer_z(_TWELVE, _flat(_TWELVE, **{"pod-4": float("nan")}))


def test_peer_z_cancels_a_common_mode_shift() -> None:
    """The property the whole approach rests on, asserted rather than assumed.

    Seasonality moves every peer together. If a uniform shift changed the
    result, peer-relative would not remove the need for a period estimate - it
    would only hide it.

    Cancellation holds while the estimator is non-degenerate. It does NOT hold
    when MAD collapses to zero, because the scale then falls back to a floor
    proportional to the values' own magnitude - see the test below, which found
    this rather than assumed it.
    """
    spread = {peer: 1.0 + index * 0.1 for index, peer in enumerate(_TWELVE)}
    spread["pod-0"] = 9.0
    shifted = {peer: value + 100.0 for peer, value in spread.items()}

    assert peer_z(_TWELVE, shifted)["pod-0"] == pytest.approx(peer_z(_TWELVE, spread)["pod-0"]), (
        "a uniform shift across every peer changed the comparison"
    )


def test_the_scale_floor_breaks_cancellation_when_mad_collapses() -> None:
    """Stated because it is a real limit of the floor, not a bug to hide.

    With identical peers MAD is exactly zero, so the scale falls to
    `min(|value|) * 1e-3` - which scales with the absolute level. A uniform
    shift then changes z, and common-mode cancellation fails precisely where
    the estimator was already degenerate.

    This is a second, independent argument for `MIN_PEERS`: a large group makes
    an exactly-zero MAD vanishingly unlikely, so the floor stops being reachable
    in practice. It also means the floor must never be read as "a small number
    that does not matter" - when it engages, it decides the answer.
    """
    identical = _flat(_TWELVE, **{"pod-0": 5.0})
    shifted = {peer: value + 100.0 for peer, value in identical.items()}

    assert peer_z(_TWELVE, identical)["pod-0"] != pytest.approx(
        peer_z(_TWELVE, shifted)["pod-0"]
    ), (
        "the floor is no longer level-dependent - if that was fixed deliberately, "
        "this test should be replaced by one asserting cancellation everywhere"
    )
