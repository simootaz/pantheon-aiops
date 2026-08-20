"""Argus's detection parameters, and the records they were derived from.

Every constant here was measured against a live Prometheus fed by the
simulator, not chosen and not derived offline. That distinction is the whole
lesson of `feature/sim-alert-rules`: every offline number that branch produced
was internally consistent, reproducible, and described a series the system
never published.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import statistics
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

#: Consecutive samples above `Z_THRESHOLD` before a point is called anomalous.
#:
#: Bound from above by the shortest contiguous elevated stretch any scenario
#: produces, which is `noisy_neighbor`: 14s at z>5, collapsing to 4s at z>8.
#: k and z* are therefore derived together - a higher z* leaves less for k to
#: fit inside. At z*=5 the worst case is 14 samples, so 5 sits comfortably
#: inside it with margin for the alignment slop a fixed sample grid imposes.
SUSTAIN_SAMPLES = 5

#: Deviations from the window's centre, in units of its scale, before a sample
#: counts. Derived from N baseline-only runs - see `FalsePositiveBound`.
#:
#: Set from `calibrate()` rather than written here, because a threshold typed
#: into a constant is a threshold nobody re-derives when the data moves.
Z_THRESHOLD = 5.0


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
    "SUSTAIN_SAMPLES",
    "WINDOW_SECONDS",
    "Z_THRESHOLD",
    "BaselineRun",
    "DegradationUnknownError",
    "DetectionCoverage",
    "FalsePositiveBound",
    "RunStatus",
    "aggregate",
    "robust_z",
]
