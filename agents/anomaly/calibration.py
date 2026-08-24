"""Argus's detection parameters, and the records they were derived from.

Every constant here was measured against a live Prometheus fed by the
simulator, not chosen and not derived offline. That distinction is the whole
lesson of `feature/sim-alert-rules`: every offline number that branch produced
was internally consistent, reproducible, and described a series the system
never published.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

#: Trailing samples used to estimate a series' own baseline, in seconds. The
#: scrape is 1s, so this is also the sample count.
#:
#: **Chosen for the lowest baseline excursion, not the largest peak.** Measured
#: across five scenarios, the highest |z| a *clean* baseline produced was
#: lowest at 90s for every metric - 4.0 / 3.2 / 3.4 / 1.4 / 0.0 against
#: 8.0 / 5.5 / 3.5 / 3.5 / 0.0 at 20-45s. A longer window estimates the centre
#: more stably, so clean data throws smaller excursions and z* can sit lower.
#:
#: Peak z would have picked the worst window. `memory_leak` peaks at **43.9**
#: with a 20s window and stays above z=5 for **2%** of its fault; it peaks at
#: 12.8 with 90s and holds for 48%. The biggest number belongs to the window
#: that detects least.
WINDOW_SECONDS = 90

#: Consecutive samples above the metric's threshold before a point is anomalous.
#:
#: Bound from above by the shortest contiguous elevated stretch any scenario
#: produces, which is `noisy_neighbor`: 14s at z>5, collapsing to 4s at z>8.
#: k and z* are therefore derived together - a higher z* leaves less for k to
#: fit inside. At z*=5 the worst case is 14 samples, so 5 sits comfortably
#: inside it with margin for the alignment slop a fixed sample grid imposes.
SUSTAIN_SAMPLES = 5

#: PLACEHOLDER. Not a derived value and not to be detected against.
#:
#: A single global threshold cannot serve these metrics: their clean-baseline
#: |z| spans **0.01 to 15.67**, three orders of magnitude. Any value clearing
#: `error_ratio` destroys detection everywhere else - `noisy_neighbor` holds
#: only 12 samples above z=6 and 4 above z=8. Thresholds are per metric, in
#: `THRESHOLDS` below, and this constant exists only so nothing silently reads
#: a global one.
Z_THRESHOLD_PLACEHOLDER = 5.0


@dataclass(frozen=True)
class MetricThreshold:
    """A per-metric threshold, and the measurement that justifies it.

    The measurement is carried, not just the number. A threshold whose basis is
    not attached is a number nobody can re-derive when the data moves - and the
    first thing anyone asks of a threshold that misfired is what it was set
    from.
    """

    #: Highest |z| this metric produced on a clean baseline, measured live.
    observed_baseline_max: float
    #: The threshold itself. Clears `observed_baseline_max` by `margin`.
    threshold: float
    #: Runs the observation is drawn from. A bound from one run is one sample.
    runs: int
    #: Conditions covered. A tight distribution over a narrow condition is not
    #: a bound over a wide one - see docs/guard-verification.md, 2026-08-20.
    conditions: str

    @property
    def margin(self) -> float:
        return self.threshold / self.observed_baseline_max if self.observed_baseline_max else 0.0


class NonFiniteSampleError(ValueError):
    """Raised when nan or inf reaches a z computation.

    `0/0` in PromQL yields NaN, and `statistics.median` propagates it without
    complaint. Every `error_ratio` row of the first peer-relative run was `nan`
    for exactly this reason, and the nan reached a results table before anyone
    noticed - the fault values printed as ordinary numbers while the scale they
    were divided by was nan-contaminated.
    """


class MetricNotCalibratedError(LookupError):
    """Raised when a metric with no measured bound is scanned."""


#: Per-metric thresholds. **A missing entry is a refusal, not a default.**
#:
#: `threshold_for` raises rather than falling back to a global value, so a
#: metric added tomorrow cannot inherit a number nobody measured for it. Same
#: shape as `BaselineRun.degraded` being `bool | None` with no default: the
#: absent case must be loud.
#:
#: `error_ratio` is deliberately ABSENT, and the reason is a property worth
#: knowing before any ratio-of-rates is added here.
#:
#: Its clean-baseline |z| was isolated one variable at a time:
#:
#:     A  speed=228  dur=150s   62 samples    |z| =  2.42
#:     B  speed=228  dur=480s  391 samples    |z| =  9.42   (duration only)
#:     C  speed=630  dur=150s   61 samples    |z| = 18.18   (speed only)
#:     D  speed=2500 dur=150s   61 samples    |z| =  4.71   (speed only, further)
#:
#: **Duration moves it** - 2.42 to 9.42 on the same clock, from six times the
#: samples. That is an ordinary tail effect and it means any bound must state
#: the duration it was drawn over.
#:
#: **Speed moves it much harder, and NOT monotonically** - 18.18 at 630x but
#: 4.71 at 2500x, both on 61 samples. A monotonic noise floor would have been
#: easy to correct for; this is aliasing. The push tick against the 1s scrape
#: gives 0.76, 2.10 and 8.33 ticks per scrape at those speeds, and the worst
#: case sits where the ratio is just past 2. The 500-status counter increments
#: rarely at baseline, so `rate()` over a 10s range sees a handful of coarse
#: jumps; when tick and scrape beat against each other the numerator alternates
#: between zero and a full step while the denominator does not.
#:
#: The gauges are untouched by all of this - `latency` stays in 2.85-4.35 and
#: `ci_ratio` in 3.17-4.72 across the same four conditions.
#:
#: > A ratio-of-rates has a **compression-dependent, non-monotonic noise
#: > floor**. Its threshold is valid only at the speed and duration it was
#: > measured at, which makes a single number for it meaningless across a gate
#: > that runs each scenario at a different compression.
#:
#: This is why counters are excluded outright and why a rate ratio is not a
#: safe substitute: the compression factor cancels in the *value* of a ratio,
#: but not in its *noise*.
#: Derived 2026-08-24. Floors from runs 1-5 of a ten-run baseline set, then
#: thresholds from runs 6-10 under those floors - so the threshold is measured
#: on runs the floor was not fitted to. Each is the smallest ladder value with
#: **zero exceedances** across roughly 2760 held-out instants.
#:
#: The bound is the rule of three, not the target that selected it: zero events
#: in n samples puts the rate below 3/n at 95%, which is **1.1e-3** here. The
#: 1e-4 in prediction 11 was a selection criterion. A rate that small cannot be
#: measured from this many samples, only bounded above.
#:
#: Conditions are 630x compression, 480s runs, and the node-disk fix applied.
#: A threshold is valid for the conditions it was measured under and no others.
THRESHOLDS: dict[str, MetricThreshold] = {
    "memory": MetricThreshold(
        observed_baseline_max=3.98,
        threshold=4.0,
        runs=5,
        conditions="630x, 480s, 12 pods, floor 4.084e+08 bytes; held out of a 10-run set",
    ),
    "cpu": MetricThreshold(
        observed_baseline_max=3.01,
        threshold=3.5,
        runs=5,
        conditions="630x, 480s, 12 pods, floor 0.1746 cores; held out of a 10-run set",
    ),
    "latency": MetricThreshold(
        observed_baseline_max=5.10,
        threshold=6.0,
        runs=5,
        conditions="630x, 480s, 12 pods, floor 0.03933 s; held out of a 10-run set",
    ),
    "disk_ratio": MetricThreshold(
        observed_baseline_max=92.77,
        threshold=100.0,
        runs=5,
        conditions="630x, 480s, 3 nodes, floor 2.953e-05 ratio; held out of a 10-run set",
    ),
    "ci_ratio": MetricThreshold(
        observed_baseline_max=19.30,
        threshold=20.0,
        runs=5,
        conditions="630x, 480s, 5 services, floor 8.634e-04 ratio; held out of a 10-run set",
    ),
    "error_ratio": MetricThreshold(
        observed_baseline_max=24.19,
        threshold=25.0,
        runs=5,
        conditions="630x, 480s, 5 services, floor 1.920e-05 ratio; held out of a 10-run set",
    ),
}


def threshold_for(metric: str) -> MetricThreshold:
    """The threshold for `metric`, or a refusal.

    Never a fallback. A metric with no measured bound is a metric Argus must
    not scan - emitting a Finding against an unmeasured threshold is exactly
    the uncalibrated number this design refuses to produce.
    """
    try:
        return THRESHOLDS[metric]
    except KeyError:
        raise MetricNotCalibratedError(
            f"{metric!r} has no measured baseline bound, so it cannot be scanned. "
            "Measure it against the live stack and add it to THRESHOLDS - do not "
            "reuse another metric's threshold, and do not fall back to a global one."
        ) from None


#: Peers a group must contain before a peer-relative comparison is attempted.
#:
#: PROVISIONAL: this is the only size measured cleanly, not a measured floor.
#: A seeded sweep (seed 20260821, 40 random subsets per size, 304 fully-covered
#: timestamps of live baseline) gives the fraction of subsets whose clean
#: baseline |z| exceeds 8:
#:
#:      3 peers  100%   median  365.01   worst 9444.81
#:      4 peers   70%   median   10.97   worst  719.88
#:      5 peers   78%   median   15.27   worst  359.87
#:      6 peers   52%   median    8.25   worst  216.40
#:      8 peers   42%   median    6.57   worst   30.70
#:     10 peers    8%   median    5.72   worst   11.97
#:     12 peers    0%   median    5.35   worst    5.35
#:
#: **The tail decides, not the median.** Three peers has a *best* subset of
#: 24.92 - so a particular small group can look perfectly well behaved while
#: every neighbouring choice is catastrophic. Sampling one group tells you
#: nothing about whether the size is safe.
#:
#: Twelve is where the exceedance reaches zero. Ten is close, and only 12 has
#: been measured as a whole population rather than sampled, so the number stays
#: provisional until the sweep is repeated across scenarios and metrics.
#: SUPERSEDED as a safety rule, 2026-08-24. Three runs of predictions - 08, 09
#: and 11 - tested whether the count is the variable, and it is not.
#:
#: `disk_ratio` at **three** nodes is calibrated and detects its scenario by
#: 101x. Two of three **twelve**-peer groups fail the same pooled-covers-worst
#: test a five-peer group passes. Peer count correlates with the threshold a
#: group needs at -0.600, too weak to be a rule.
#:
#: What the count was standing in for is the number of RUNS: a bound from one
#: run is one sample of a distribution whose worst case decides safety. See
#: `MIN_CALIBRATION_RUNS`.
#:
#: Three is what remains, and it is arithmetic rather than a safety margin: a
#: median and a MAD over fewer than three values describe nothing. Safety comes
#: from the calibrated threshold in `THRESHOLDS`, which a group either has or
#: does not.
MIN_PEERS = 3

#: Runs a threshold must be derived over before it may be written down.
#:
#: Measured in prediction 11: five of six groups settle by N = 4, and N = 2 does
#: not - it put `ci_ratio` at 150 against a settled 40, and `disk_ratio` at 12
#: against 9. A pooled bound at 1e-3 failed to cover its own worst run for five
#: of six groups, which is what makes a single run's number unusable.
MIN_CALIBRATION_RUNS = 4


#: Per-metric scale floors. **A missing entry is a refusal, not a default.**
#:
#: The floor is the third parameter of this method, alongside the window and the
#: threshold, and it was the one nobody derived. It sat inside the estimator as
#: `min(|value|) * 1e-3` - a heuristic, never measured, and invisible in every
#: result it produced.
#:
#: It is not a small correction. When the scale collapses the floor decides the
#: answer outright: `disk_ratio` over three nodes gave **1599.63 on a clean
#: baseline** and **1585.74 as a signal**, and both numbers were the floor
#: speaking rather than the data. A parameter that can determine the output must
#: be derived and stated like any other.
#:
#: Empty because nothing has been measured yet. `floor_for` refuses rather than
#: substituting a plausible constant, for the same reason `THRESHOLDS` does.
#: Measured 2026-08-24 as the **5th percentile of the observed scale
#: distribution** over five baseline runs, so the floor engages 5% of the time
#: by construction. Held-out engagement came in at 4.6% to 5.3%.
#:
#: What it replaces, and why: `min(|value|) * 1e-3` scales with a metric's
#: LEVEL rather than its dispersion. Measured over 5525 instants it never
#: engaged at all for memory, cpu, latency or ci_ratio, and engaged on **46.9%**
#: of `disk_ratio` instants - because disk sits at 0.34 with a dispersion near
#: 3.7e-04, some 900x smaller. One heuristic, inert for five metrics and
#: dominant for the sixth.
#:
#: Changing it moved every threshold: `ci_ratio` from 150 to 20 and
#: `error_ratio` from 100 to 25, because a floor large enough to catch a
#: collapsing MAD suppresses exactly the excursions that set those numbers.
#: Much of what records 08 to 11 read as "small groups are dangerous" was the
#: floor being too small to catch the collapse.
#:
#: In the metric's own units, not in z.
SCALE_FLOORS: dict[str, float] = {
    "memory": 4.08355e08,
    "cpu": 0.174567,
    "latency": 0.0393306,
    "disk_ratio": 2.95257e-05,
    "ci_ratio": 8.63377e-04,
    "error_ratio": 1.92034e-05,
}


class ScaleFloorNotMeasuredError(LookupError):
    """Raised when a metric's scale floor has never been measured."""


def floor_for(metric: str) -> float:
    """The measured scale floor for `metric`, or a refusal.

    Never a heuristic. A floor guessed from the data's own magnitude makes the
    result depend on the absolute level - which is exactly how common-mode
    cancellation breaks, and it breaks precisely when the estimator is already
    degenerate.
    """
    try:
        return SCALE_FLOORS[metric]
    except KeyError:
        raise ScaleFloorNotMeasuredError(
            f"{metric!r} has no measured scale floor. The floor decides the answer whenever "
            "the scale collapses, so it cannot be guessed - measure it against the live "
            "stack and add it to SCALE_FLOORS."
        ) from None


@dataclass(frozen=True)
class PeerComparison:
    """A peer-relative reading, and whether it can be read as a measurement.

    `floor_engaged` is carried rather than inferred. A z produced under a
    collapsed scale is determined by the floor, and downstream has no way to
    tell that from the number alone.
    """

    z: dict[str, float]
    centre: float
    scale: float
    floor_engaged: bool


class InsufficientPeersError(ValueError):
    """Raised when a peer group is too small to support the estimator."""


class PartialPeerCoverageError(ValueError):
    """Raised when some expected peer did not report at this instant."""


def peer_z(
    peers: Sequence[str], samples: Mapping[str, float], *, scale_floor: float
) -> PeerComparison:
    """Peer-relative deviation at ONE instant. No window, no history, no period.

    Seasonality is common-mode across peers, so comparing a series against its
    peers cancels the diurnal component without knowing the period - which is
    what makes this attractive where a trailing window needs a period estimate
    that production does not supply.

    Two preconditions, both hard. Neither is a filter to relax:

    **Group size.** Below `MIN_PEERS` the estimator degenerates. With three
    peers MAD is the median of three deviations and hits exactly zero whenever
    two agree, dropping the scale to its floor and sending z wherever the floor
    implies. Measured on clean data, three peers exceeded |z| = 8 in 100% of
    sampled subsets, worst case 9444 - and `disk_ratio` at three nodes duly
    produced 1599.63 on a clean baseline in one scenario and 1585.74 as a
    "signal" in another. The same degeneracy with opposite labels.

    **Complete coverage.** Every expected peer must have reported. Comparing
    whichever peers happened to arrive is not a smaller comparison of the same
    thing - it silently becomes a different, smaller group, with the size
    behaviour above. That is a precondition rather than a filter because the
    failure is invisible in the output: the numbers look ordinary.
    """
    if len(peers) < MIN_PEERS:
        raise InsufficientPeersError(
            f"{len(peers)} peers, below the measured minimum of {MIN_PEERS}. A group this "
            "small produces a degenerate scale, and the resulting z is a property of the "
            "floor rather than of the data. Widen the peer set or use a temporal comparison."
        )

    missing = [peer for peer in peers if peer not in samples]
    if missing:
        raise PartialPeerCoverageError(
            f"{len(missing)} of {len(peers)} peers did not report: {sorted(missing)[:5]}. "
            "Comparing the peers that did arrive is a comparison of a different, smaller "
            "group - and nothing in the result would say so."
        )

    values = [samples[peer] for peer in peers]
    non_finite = [
        peer for peer, value in zip(peers, values, strict=True) if not math.isfinite(value)
    ]
    if non_finite:
        raise NonFiniteSampleError(
            f"non-finite sample(s) from {sorted(non_finite)[:5]}. See NonFiniteSampleError."
        )

    centre = statistics.median(values)
    mad = statistics.median([abs(value - centre) for value in values])
    spread = 1.4826 * mad
    floor_engaged = spread < scale_floor
    scale = max(spread, scale_floor)
    return PeerComparison(
        z={peer: (samples[peer] - centre) / scale for peer in peers},
        centre=centre,
        scale=scale,
        floor_engaged=floor_engaged,
    )


class DetectionCoverage(StrEnum):
    """How much of a fault this method actually sees, per scenario shape.

    Stated because it is a property of a trailing-window estimator, not a
    tuning failure, and no window length hides it.
    """

    #: z stays above threshold across most of the fault.
    SUSTAINED = "sustained"

    #: z spikes at onset and then collapses, because the fault outlasts the
    #: window and becomes the window's own baseline. MAD's 50% breakdown point
    #: protects the estimate only while the deviation occupies under half the
    #: window; past that the centre walks up to meet it.
    ONSET_ONLY = "onset_only"


#: What the live sweep measured, per scenario. Recorded so the limitation is
#: visible where the constants are, not only in a report someone has to find.
#:
#: `disk_pressure` is the stark case: a **peak z of 700 against a tail z of
#: 1.4** at this window. The disk fills monotonically for 105 wall seconds;
#: once the window sits entirely inside the ramp, the median tracks it and the
#: signal vanishes. Widening the window does not rescue it - at 180s coverage
#: falls to 9%, because the window stops fitting inside the run.
#:
#: An incident detector that fires once at onset is still useful. One that
#: silently stops is not, which is why this is a declared property.
MEASURED_COVERAGE: dict[str, DetectionCoverage] = {
    "bad_deploy_5xx": DetectionCoverage.SUSTAINED,
    "noisy_neighbor": DetectionCoverage.SUSTAINED,
    "flaky_test_storm": DetectionCoverage.SUSTAINED,
    "memory_leak": DetectionCoverage.SUSTAINED,
    "disk_pressure": DetectionCoverage.ONSET_ONLY,
}


class RunStatus(StrEnum):
    """Where a measurement run got to."""

    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class BaselineRun:
    """One baseline-only run, and whether it met the conditions it characterises.

    `degraded` is deliberately `bool | None` with no default. `None` means
    nobody recorded it, and `aggregate` refuses that - see
    `DegradationUnknownError`. A default of `False` would let an unrecorded run
    be counted as clean, which is the failure this type exists to prevent.
    """

    index: int
    status: RunStatus
    degraded: bool | None
    max_abs_z: dict[str, float] = field(default_factory=dict)
    min_nonzero_scale: float | None = None
    note: str = ""


class DegradationUnknownError(ValueError):
    """Raised when an aggregate is asked for over runs of unknown condition."""


@dataclass(frozen=True)
class FalsePositiveBound:
    """The highest |z| a clean baseline produced, and what it was computed over.

    Carries the degraded count rather than hiding it, and reports the bound
    twice - across every run, and across the clean subset. If those differ
    materially, the difference is a finding about how much a degraded run
    perturbs the baseline, and it should be visible before anything ships on
    the number.
    """

    runs_total: int
    runs_degraded: int
    highest_abs_z_all: float
    highest_abs_z_clean: float | None
    per_metric_all: dict[str, float]
    smallest_scale: float | None

    @property
    def materially_different(self) -> bool:
        """Whether excluding the degraded runs moves the bound enough to matter.

        10% is a stated line, not a derived one: with ten runs the bound's own
        granularity is coarse, and a difference under that is inside the noise
        of the sample size rather than evidence about degradation.
        """
        if self.highest_abs_z_clean is None or not self.highest_abs_z_all:
            return False
        gap = abs(self.highest_abs_z_all - self.highest_abs_z_clean)
        return gap / self.highest_abs_z_all > 0.10


def aggregate(runs: list[BaselineRun]) -> FalsePositiveBound:
    """Combine baseline runs into a bound, refusing runs of unknown condition.

    The rule this enforces: **an aggregate cannot be computed from run records
    without their degradation status attached.** A false-positive bound over
    ten runs of which three had no logs is still usable; a bound that does not
    say which three is not, because nobody downstream can tell whether they are
    reading the system or an artefact of a broken sink.

    Same shape as `Verdict` requiring plan steps: a result that cannot be read
    without knowing what actually ran should not be constructible.
    """
    if not runs:
        raise ValueError("no runs to aggregate")

    unknown = [run.index for run in runs if run.degraded is None]
    if unknown:
        raise DegradationUnknownError(
            f"runs {unknown} carry no degradation status. An aggregate over runs whose "
            "conditions are unknown describes neither the system nor the failure - "
            "record `degraded` on each run, or exclude it deliberately."
        )

    unfinished = [run.index for run in runs if run.status is not RunStatus.COMPLETE]
    if unfinished:
        raise DegradationUnknownError(
            f"runs {unfinished} are not COMPLETE. A partial run has measured part of a "
            "baseline, and its maximum is not comparable with a whole one."
        )

    clean = [run for run in runs if not run.degraded]
    highest = max(max(run.max_abs_z.values(), default=0.0) for run in runs)
    highest_clean = (
        max(max(run.max_abs_z.values(), default=0.0) for run in clean) if clean else None
    )
    metrics = {name for run in runs for name in run.max_abs_z}
    scales = [run.min_nonzero_scale for run in runs if run.min_nonzero_scale is not None]

    return FalsePositiveBound(
        runs_total=len(runs),
        runs_degraded=sum(1 for run in runs if run.degraded),
        highest_abs_z_all=highest,
        highest_abs_z_clean=highest_clean,
        per_metric_all={
            name: max(run.max_abs_z.get(name, 0.0) for run in runs) for name in sorted(metrics)
        },
        smallest_scale=min(scales) if scales else None,
    )


def robust_z(values: list[float], window: int, scale_floor: float) -> list[float]:
    """Rolling median/MAD z. Point i is judged against the `window` points before it.

    Strictly backward-looking: a window centred on the sample under test lets an
    anomaly pull its own baseline, which is a smaller version of the
    contamination MAD exists to resist.

    `scale_floor` keeps a flat series finite. `restarts` sits at exactly zero
    through a clean baseline, where MAD is 0 and every deviation divides by
    nothing.
    """
    non_finite = [i for i, v in enumerate(values) if not math.isfinite(v)]
    if non_finite:
        raise NonFiniteSampleError(
            f"{len(non_finite)} non-finite sample(s) at index {non_finite[:5]} reached a z "
            "computation. NaN propagates silently through median and MAD, so a centre and "
            "scale derived from it are nan and every comparison against them is False - a "
            "number that looks like a measurement and is not. Drop or define the undefined "
            "samples before calling this."
        )

    out: list[float] = []
    for index, value in enumerate(values):
        if index < window:
            out.append(0.0)
            continue
        past = values[index - window : index]
        centre = statistics.median(past)
        mad = statistics.median([abs(point - centre) for point in past])
        out.append((value - centre) / max(1.4826 * mad, scale_floor))
    return out


__all__ = [
    "MEASURED_COVERAGE",
    "MIN_PEERS",
    "SCALE_FLOORS",
    "SUSTAIN_SAMPLES",
    "THRESHOLDS",
    "WINDOW_SECONDS",
    "Z_THRESHOLD_PLACEHOLDER",
    "BaselineRun",
    "DegradationUnknownError",
    "DetectionCoverage",
    "FalsePositiveBound",
    "InsufficientPeersError",
    "MetricNotCalibratedError",
    "MetricThreshold",
    "NonFiniteSampleError",
    "PartialPeerCoverageError",
    "PeerComparison",
    "RunStatus",
    "ScaleFloorNotMeasuredError",
    "aggregate",
    "floor_for",
    "peer_z",
    "robust_z",
    "threshold_for",
]
