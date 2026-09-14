"""The projection: a slope, a crossing time, and how much to believe them.

THREE NUMBERS, TWO OF THEM DEFINITIONS
----------------------------------------
`rate_per_hour` is a least-squares slope. That is what "rate" means, and any
other estimator would need an argument this one does not. `time_to_limit_hours`
is `(limit - current) / rate`. That is what "time to limit" means. Neither is a
judgement, and neither has a parameter.

`r2` is the third number and the only one where a forecaster gets to lie. A
slope fitted through noise is a slope, and reported alone it reads like a trend.
So the fit quality travels with the projection rather than being used to
suppress it - a caller that wants to draw a line at 0.9 can, and a reader who
disagrees with that line can see what was fitted.

WHAT "NOT FILLING" MEANS HERE
-------------------------------
A slope at or below zero, or a positive slope that reaches the limit only after
`horizon_hours`, is a resource that is not filling on any timescale this
forecast is about. `crossing_within` is False for both, and the agent treats
that as a clean window: a result, not a Finding. Reporting "time to full: 1 400
hours" as a risk would be reporting the generator's accumulation term, and in a
real cluster it would be reporting the fact that disks fill eventually.

WHY THE FIT IS AGAINST HOURS FROM THE FIRST SAMPLE
----------------------------------------------------
Fitting against absolute epoch seconds puts x values around 1.7e9 and the
normal equations lose digits in the subtraction. Re-basing to the first sample
costs nothing and the slope is the same line.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.contracts.evidence import MetricSample

#: Fewer points than this is not a trend, it is a pair. Two points always fit a
#: line perfectly, and R² of 1.0 on two points would report certainty about
#: nothing.
MIN_SAMPLES = 3

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True)
class Forecast:
    """One resource's projection over one window."""

    #: The fitted value at the last sample. Fitted rather than observed, so a
    #: single noisy final sample does not set the starting point of the
    #: projection.
    current: float
    limit: float
    rate_per_hour: float
    r2: float
    #: Hours from the last sample until the fitted line reaches `limit`. None
    #: when the slope is zero or negative - a line going the other way never
    #: gets there, and "infinite" is not a number a contract can carry.
    time_to_limit_hours: float | None
    samples: int
    window_seconds: int

    def crossing_within(self, horizon_hours: float) -> bool:
        """Whether the projection reaches the limit inside the horizon."""
        return self.time_to_limit_hours is not None and self.time_to_limit_hours <= horizon_hours


class NotEnoughSamples(ValueError):
    """A window too short to fit. Distinct from a clean window."""


def fit(samples: list[MetricSample], *, limit: float) -> Forecast:
    """Fit a line through the samples and project it to the limit.

    Raises `NotEnoughSamples` below `MIN_SAMPLES`, rather than returning a
    projection with an R² of 1.0 through two points. The agent turns that into
    a DEGRADED refusal, because "the window was too short to say" and "the
    window was clean" are different facts.
    """
    if len(samples) < MIN_SAMPLES:
        raise NotEnoughSamples(
            f"{len(samples)} sample(s); a trend needs at least {MIN_SAMPLES}. Two "
            "points fit a line perfectly and say nothing."
        )

    ordered = sorted(samples, key=lambda sample: sample.at)
    origin = ordered[0].at
    xs = [_hours_since(origin, sample.at) for sample in ordered]
    ys = [sample.value for sample in ordered]

    n = float(len(xs))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))

    if sxx == 0.0:
        # Every sample at the same instant. A slope over zero elapsed time is
        # undefined, and the samples are not a window.
        raise NotEnoughSamples("every sample carries the same timestamp, so no time elapsed")

    slope = sxy / sxx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    # A flat series has ss_tot == 0 and the line explains it exactly. Reporting
    # R² = 0 there would call a perfect fit a bad one.
    r2 = 1.0 if ss_tot == 0.0 else max(0.0, 1.0 - ss_res / ss_tot)

    last_x = xs[-1]
    current = intercept + slope * last_x

    if slope > 0.0 and current < limit:
        time_to_limit: float | None = (limit - current) / slope
    elif slope > 0.0:
        # Already at or past the limit and still rising. Zero rather than
        # negative: "it happened some time ago" is a different question.
        time_to_limit = 0.0
    else:
        time_to_limit = None

    return Forecast(
        current=current,
        limit=limit,
        rate_per_hour=slope,
        r2=r2,
        time_to_limit_hours=time_to_limit,
        samples=len(ordered),
        window_seconds=round(last_x * SECONDS_PER_HOUR),
    )


def _hours_since(origin: datetime, at: datetime) -> float:
    return (at - origin).total_seconds() / SECONDS_PER_HOUR


__all__ = ["MIN_SAMPLES", "Forecast", "NotEnoughSamples", "fit"]
