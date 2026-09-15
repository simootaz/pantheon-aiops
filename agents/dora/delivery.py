"""Delivery measurements from pull requests, named for what they actually are.

TWO OF THE FOUR DORA METRICS ARE NOT REACHABLE FROM HERE
----------------------------------------------------------
* **Change failure rate** needs to know which deployments caused an incident.
  Nothing in this system links a deployment to an incident.
* **Time to restore service** needs an incident's start and end. Nothing records
  either.

Both are omitted rather than approximated. A change-failure rate computed from
"pull requests that were later reverted" measures reverts, and a team that fixes
forward would score perfectly while breaking production every week.

REVIEW LATENCY IS NOT LEAD TIME, AND THE DIFFERENCE IS THE WHOLE POINT
------------------------------------------------------------------------
DORA's **lead time for changes** runs from the first commit to the change
running in production. What a pull request carries is `created_at` to
`merged_at`: how long a review took.

Those differ by the time before the PR was opened and by the whole deploy
pipeline after it merged - which for most teams is the majority of the interval.
Reporting review latency as lead time makes a team look fast by measuring a
shorter thing, and it is the most common misuse of these numbers.

So this module computes `review_latency` and says so in the name. Nothing here
emits a DORA performance band: elite/high/medium/low are defined against lead
time to production, and assigning one from review latency would be the same
misuse wearing a label.

MERGE FREQUENCY IS A PROXY, AND IT IS LABELLED ONE
----------------------------------------------------
Deployment frequency needs deployments. Merges to the default branch are a proxy
only if every merge deploys, which is a claim about a team's pipeline rather
than about this data - so the field is `merge_frequency_per_week`.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

#: Below this many merged pull requests, a median is a description of two or
#: three reviews rather than of how the team works.
#:
#: Not a tuned threshold: it is the point below which the statistic has no
#: subject, and the agent reports the count instead of a percentile.
MIN_MERGED_FOR_A_PERCENTILE = 5


@dataclass(frozen=True)
class Merged:
    """One merged pull request, reduced to the two instants that matter."""

    number: int
    opened_at: datetime
    merged_at: datetime

    @property
    def review_hours(self) -> float:
        return (self.merged_at - self.opened_at).total_seconds() / 3600.0


@dataclass(frozen=True)
class Delivery:
    """What the window supports saying, and nothing more."""

    window_days: float
    merged: int
    #: Merges per week. A PROXY for deployment frequency - see the module
    #: docstring - and named so nobody has to remember that.
    merge_frequency_per_week: float
    #: `None` below `MIN_MERGED_FOR_A_PERCENTILE`. A median of three reviews is
    #: a fact about three reviews.
    median_review_hours: float | None
    slowest_review_hours: float | None

    @property
    def has_percentiles(self) -> bool:
        return self.median_review_hours is not None


def merged_from(payloads: list[dict[str, object]]) -> list[Merged]:
    """Every genuinely merged pull request in a GitHub `pulls` listing.

    A closed pull request with no `merged_at` was **closed without merging**,
    and counting it would inflate both numbers: the frequency by work that never
    shipped, and the latency by however long an abandoned branch sat open.
    """
    merged: list[Merged] = []
    for payload in payloads:
        opened, closed = payload.get("created_at"), payload.get("merged_at")
        number = payload.get("number")
        if (
            not isinstance(number, int)
            or not isinstance(opened, str)
            or not isinstance(closed, str)
        ):
            continue
        try:
            opened_at = datetime.fromisoformat(opened.replace("Z", "+00:00"))
            merged_at = datetime.fromisoformat(closed.replace("Z", "+00:00"))
        except ValueError:
            continue
        if merged_at < opened_at:
            # Clock skew, or a payload nobody should trust. A negative review
            # time would drag a median below zero and read as instant approval.
            continue
        merged.append(Merged(number=number, opened_at=opened_at, merged_at=merged_at))
    return merged


def measure(merged: list[Merged], *, window: timedelta) -> Delivery:
    """What this window of merged pull requests supports.

    The window is passed in rather than derived from the data. Deriving it from
    the first and last merge would make a quiet fortnight look like a busy day:
    two merges an hour apart would report a frequency of 336 a week.
    """
    days = window.total_seconds() / 86400.0
    per_week = (len(merged) / days * 7.0) if days > 0 else 0.0

    if len(merged) < MIN_MERGED_FOR_A_PERCENTILE:
        return Delivery(
            window_days=days,
            merged=len(merged),
            merge_frequency_per_week=per_week,
            median_review_hours=None,
            slowest_review_hours=None,
        )

    hours = sorted(one.review_hours for one in merged)
    return Delivery(
        window_days=days,
        merged=len(merged),
        merge_frequency_per_week=per_week,
        median_review_hours=_median(hours),
        slowest_review_hours=hours[-1],
    )


def _median(sorted_hours: list[float]) -> float:
    """The middle value, averaging the two middles on an even count.

    A median rather than a mean: one pull request left open over a holiday
    moves a mean by days and a median not at all, and the question being asked
    is what a typical review takes.
    """
    middle = len(sorted_hours) // 2
    if len(sorted_hours) % 2:
        return sorted_hours[middle]
    return (sorted_hours[middle - 1] + sorted_hours[middle]) / 2.0
