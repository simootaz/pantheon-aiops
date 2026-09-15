"""Themis - measures what delivery data supports, and refuses the rest.

WHAT IT REPORTS
-----------------
Merge frequency and review latency, over a window, from merged pull requests.
Both are named for what they are rather than for the DORA metric they resemble -
see `delivery.py` for why that distinction is the whole agent.

WHAT IT DOES NOT REPORT, AND WHY THAT IS NOT A GAP TO FILL LATER
------------------------------------------------------------------
* **Change failure rate** and **time to restore** need incidents linked to
  deployments. Nothing in this system records either.
* A **DORA performance band** - elite, high, medium, low. Those are defined
  against lead time to production, and this agent has review latency. Assigning
  a band from it would be the misuse the module exists to avoid.
* A **trend**. `assess_delivery_trend` was in the manifest and is gone.

The trend one is worth stating plainly, because it is the same mistake Lethe
already made and deleted. Comparing this window's median against the previous
window's measures the difference between two small samples, and
`docs/lethe-predictions/02-surprise-and-surge.md` records what that produced
there: two CLEAN baselines differed by 1.29x while five real faults topped out
at 1.31x-1.54x, so a fault was not distinguishable from no fault.

The same arithmetic applies here with fewer data points. A team merging twelve
pull requests a fortnight cannot have a trend measured from twelve pull
requests, and reporting one would be reporting noise with a direction attached.

No LLM is involved. `Finding.rationale` is optional, so a templated title and
real Evidence are a complete claim - the same choice as Argus, Lethe, Aegis and
Hephaestus.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.dora.delivery import MIN_MERGED_FOR_A_PERCENTILE, Delivery, measure, merged_from
from agents.dora.tools import attach
from core.contracts.evidence import (
    Evidence,
    EvidenceSource,
    PipelineRunPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity

_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/themis/evidence")

#: How far back to read. A quota bound and a sample-size floor at once: shorter
#: windows produce medians of three reviews, which `delivery.py` refuses to
#: compute anyway.
DEFAULT_WINDOW = timedelta(days=28)

#: Pull requests to read. GitHub caps a page at 100, and a team merging more
#: than that in four weeks gets a measurement over the most recent 100 - which
#: is reported rather than silently truncated.
MAX_PULL_REQUESTS = 100

#: The same for every measurement. A slow review is not an incident, and
#: ranking one against another would need a target this agent has not been
#: given - "is 30 hours bad" is a question about a team, not about data.
DELIVERY_SEVERITY = Severity.LOW


class Themis(BaseAgent):
    """The delivery side. Measures merge frequency and review latency."""

    domain = "dora"

    def bind_tools(self, tools: Any) -> None:
        attach(tools)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Measure the window, or say why it could not be measured.

        Returns one Finding. Not zero: unlike a detector, this agent is asked a
        question and always has an answer, even when the answer is "four merges
        in four weeks, which is too few to say anything about review time".
        """
        repository = str(ctx.params.get("repository", ""))
        if not repository:
            raise AgentDegraded(
                "no repository was named. Themis reads `repository` off ctx.params - "
                "a delivery measurement with no project is not an empty result.",
                partial=[],
                retryable=False,
            )

        window = _window_of(ctx)

        # `state=closed` returns the whole history newest-first, so the window
        # is applied here. GitHub has no "merged after" filter on this endpoint,
        # and without this a four-week measurement reports four years.
        payloads = await ctx.tools.call(
            "github.pull_requests", repository=repository, state="closed"
        )
        merged = [
            one
            for one in merged_from(_listing(payloads))
            if one.merged_at >= ctx.window_end - window
        ]

        delivery = measure(merged, window=window)
        return [self._finding(ctx, delivery, repository)]

    def _finding(self, ctx: AgentContext, delivery: Delivery, repository: str) -> Finding:
        subject = ResourceRef(kind="repository", name=repository)
        return Finding(
            id=ctx.investigation_id,
            agent=self.codename,
            kind=FindingKind.OBSERVATION,
            title=_headline(delivery, repository),
            severity=DELIVERY_SEVERITY,
            # Read off timestamps, not inferred from them. What is uncertain is
            # whether the numbers mean the team is fast, and this agent does not
            # make that claim.
            confidence=1.0,
            detected_at=ctx.window_end,
            window_start=ctx.window_end - timedelta(days=delivery.window_days),
            window_end=ctx.window_end,
            subject=subject,
            evidence=[
                Evidence(
                    id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:delivery"),
                    source=EvidenceSource(
                        connector="github", query=f"pulls?state=closed&repo={repository}"
                    ),
                    observed_at=ctx.window_end,
                    summary=_summary(delivery),
                    subject=subject,
                    payload=PipelineRunPayload(
                        pipeline_id="",
                        project=repository,
                        ref="",
                        status="measured",
                        failed_jobs=[],
                    ),
                )
            ],
            tags=["delivery", "merge-frequency"],
        )


def _window_of(ctx: AgentContext) -> timedelta:
    """The measurement window, from params or the default.

    Taken from `ctx.params` rather than from `ctx.window_start` because the
    investigation window is minutes - the span an alert is about - and a
    delivery measurement over ten minutes is a measurement of nothing.
    """
    days = ctx.params.get("window_days")
    return timedelta(days=float(days)) if isinstance(days, int | float) else DEFAULT_WINDOW


def _listing(payloads: Any) -> list[dict[str, Any]]:
    if isinstance(payloads, list):
        return [one for one in payloads if isinstance(one, dict)][:MAX_PULL_REQUESTS]
    return []


def _headline(delivery: Delivery, repository: str) -> str:
    if not delivery.has_percentiles:
        return (
            f"{repository}: {delivery.merged} merges in "
            f"{delivery.window_days:.0f} days, too few to time a review"
        )
    return (
        f"{repository}: {delivery.merge_frequency_per_week:.1f} merges a week, "
        f"median review {delivery.median_review_hours:.0f}h"
    )


def _summary(delivery: Delivery) -> str:
    """One line, with the caveats attached rather than assumed known."""
    proxy = (
        "merge frequency is a PROXY for deployment frequency - it is the real "
        "thing only if every merge deploys, which is a claim about the pipeline "
        "rather than about this data"
    )
    if not delivery.has_percentiles:
        return (
            f"{delivery.merged} merged pull requests in {delivery.window_days:.0f} days, "
            f"below the {MIN_MERGED_FOR_A_PERCENTILE} a median needs to describe how "
            f"the team works rather than how those {delivery.merged} went. {proxy}."
        )
    return (
        f"{delivery.merged} merges over {delivery.window_days:.0f} days "
        f"({delivery.merge_frequency_per_week:.1f} a week). Review latency: median "
        f"{delivery.median_review_hours:.1f}h, slowest {delivery.slowest_review_hours:.1f}h. "
        "Review latency is NOT DORA lead time - lead time runs from first commit to "
        f"production, and this is open-to-merge. {proxy}."
    )
