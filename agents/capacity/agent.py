"""Moira - says when a filling resource crosses its limit.

WHAT THIS DOES, AND WHAT IT DOES NOT
--------------------------------------
Argus says something is wrong now. Moira says when something will be. It fits a
line through a resource that has a limit and reports the crossing time - the
question `simulator/scenarios/disk_pressure.yaml` names as the interesting one
in its own header.

It projects to the metric's OWN limit and never to a substitute. A disk is full
at used == total, so that is the line. Eviction happens earlier, at a kubelet
threshold this agent cannot read, and projecting to a default of 85 % would be
projecting to a number that means something else on every cluster where the
operator set it differently. The Finding says "full", the payload carries the
limit it used, and a reader who knows the eviction threshold can subtract.

WHAT IT REFUSES, AND SAYS SO
------------------------------
A resource with no limit metric. `pantheon_pod_memory_working_set_bytes` has no
limit beside it, and the connector that would read a container's limit is not
reachable - so memory is DEGRADED on every run, including the memory-leak
scenario a capacity forecaster most obviously ought to catch. That miss is
predicted in `docs/moira-predictions/01-disk-time-to-full.md` rather than
papered over with the node's total, which is a different number.

Refusals go through `AgentDegraded` with the disk projections as `partial`, the
same way Argus reports an uncalibrated metric: an agent that quietly skipped
memory would be indistinguishable from one that looked and found no trend.

WHAT A CLEAN WINDOW IS
------------------------
A resource whose fitted line reaches its limit after `HORIZON_HOURS`, or never,
is not filling on any timescale this run is about. That is a result, not a
Finding: the generator adds a per-day accumulation to every disk, real disks
fill eventually, and reporting "time to full: 1 400 hours" as a risk on every
alert is how a reader learns to skip Moira's row.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.capacity.forecast import Forecast, NotEnoughSamples, fit
from agents.capacity.tools import attach
from core.contracts.evidence import (
    CapacityForecastPayload,
    Evidence,
    EvidenceSource,
    MetricSample,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity

_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/moira/evidence")

#: How far ahead counts. Three days: `disk_pressure` fills over three and calls
#: itself a slow burn, and a projection further out than that is reporting
#: that disks fill. On the Finding as a tag, so a reader can disagree with it.
HORIZON_HOURS = 72.0

#: Seconds between samples. A fill measured in hours does not need a
#: per-second series, and Prometheus caps range queries at 11 000 points.
STEP_SECONDS = 60

#: How far back Moira reads, regardless of the incident window it was handed.
#:
#: The context window is the incident's - five minutes by default, which is the
#: right window for "what just moved". A trend is a different question: on a
#: disk filling over three days, five minutes of samples is noise with a slope
#: through it, and the fit would report the noise. So Moira reads its own
#: window ending at the incident's end, and the Finding carries the window it
#: actually read rather than the one it was given.
LOOKBACK_HOURS = 24.0

#: Severity is constant, for the reason Argus's is: ranking risks means
#: deciding that six hours to full matters more than sixty, and at what point,
#: and that is a band nobody here has measured. The number that would rank
#: them - `time_to_limit_hours` - is on the Evidence.
FORECAST_SEVERITY = Severity.MEDIUM


@dataclass(frozen=True)
class LimitedResource:
    """A metric that has a limit, and where the limit comes from.

    `used` and `total` are separate queries rather than a pre-divided ratio,
    so the payload can say what the limit IS in the metric's unit - "full at
    214 GB" reads; "full at 1.0" does not. The projection is done on the ratio
    so the fit is unit-free and the horizon means the same thing on every node.
    """

    name: str
    used: str
    total: str
    label: str
    unit: str
    resource_kind: str


#: Every resource Moira knows the limit of. There is one, and the docstring on
#: `tools.py` says what adds the second.
RESOURCES: dict[str, LimitedResource] = {
    "disk": LimitedResource(
        name="disk",
        used="pantheon_node_disk_used_bytes",
        total="pantheon_node_disk_total_bytes",
        label="node",
        unit="bytes",
        resource_kind="node",
    ),
}

#: Resources Moira is asked about and cannot answer for, and why. Spelled out
#: rather than left absent from `RESOURCES`: absent reads as "nobody thought of
#: it", and this is "somebody did, and here is what is missing".
UNLIMITED: dict[str, str] = {
    "memory": (
        "pantheon_pod_memory_working_set_bytes has no limit metric beside it, and the "
        "Kubernetes connector that would read a container's limit is not reachable. "
        "Projecting against the node's total would be projecting to a different number."
    ),
}


class Moira(BaseAgent):
    """Capacity forecasting from Prometheus alone, and honest about the rest."""

    domain = "capacity"

    def bind_tools(self, tools: Any) -> None:
        attach(tools)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """A Finding per member whose trend reaches its limit inside the horizon.

        Always raises `AgentDegraded` with the projections as `partial`, because
        `UNLIMITED` is never empty today: every run is partial for memory, and a
        run that reported itself whole would be claiming to have looked.
        """
        findings: list[Finding] = []
        refusals = [f"{name}: {why}" for name, why in sorted(UNLIMITED.items())]
        reached_prometheus = False

        for name in sorted(RESOURCES):
            resource = RESOURCES[name]
            try:
                used = await self._series(ctx, resource.used, resource.label)
                total = await self._series(ctx, resource.total, resource.label)
            except Exception as error:
                refusals.append(f"{name}: query failed: {error}")
                continue
            reached_prometheus = True

            for member in sorted(set(used) & set(total)):
                samples, limit = _ratio_series(used[member], total[member])
                try:
                    forecast = fit(samples, limit=1.0)
                except NotEnoughSamples as short:
                    refusals.append(f"{name} on {resource.label}={member}: {short}")
                    continue
                if not forecast.crossing_within(HORIZON_HOURS):
                    continue  # a clean window: not filling on this timescale
                findings.append(self._risk(ctx, resource, member, forecast, samples, limit))

        if not reached_prometheus:
            raise AgentDegraded(
                "no resource could be fetched from Prometheus, so nothing was projected. "
                "This is an inability to look, not an absence of trends.",
                retryable=True,
                partial=findings,
            )
        raise AgentDegraded(
            f"{len(refusals)} resource(s) were not projected, so this run is partial and "
            "a quiet result for them means nothing: " + "; ".join(refusals),
            retryable=False,
            partial=findings,
        )

    async def _series(
        self, ctx: AgentContext, query: str, label: str
    ) -> dict[str, dict[float, float]]:
        raw = await ctx.tools.call(
            "prometheus.query_range",
            query=query,
            start=_lookback_start(ctx).timestamp(),
            end=ctx.window_end.timestamp(),
            step=f"{STEP_SECONDS}s",
        )
        return _parse(raw, label)

    def _risk(
        self,
        ctx: AgentContext,
        resource: LimitedResource,
        member: str,
        forecast: Forecast,
        samples: list[MetricSample],
        limit_in_unit: float,
    ) -> Finding:
        subject = ResourceRef(kind=resource.resource_kind, name=member)
        hours = forecast.time_to_limit_hours
        assert hours is not None  # crossing_within was True

        payload = CapacityForecastPayload(
            metric=f"{resource.used} / {resource.total}",
            unit="ratio",
            samples=samples,
            current=forecast.current,
            limit=forecast.limit,
            rate_per_hour=forecast.rate_per_hour,
            fit_r2=forecast.r2,
            time_to_limit_hours=hours,
            window_seconds=forecast.window_seconds,
        )
        evidence = Evidence(
            id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:{resource.name}:{member}"),
            source=EvidenceSource(
                connector="prometheus",
                query=payload.metric,
                collected_at=datetime.now(tz=UTC),
            ),
            observed_at=samples[-1].at,
            summary=(
                f"{resource.label}={member} is {forecast.current:.1%} full and filling at "
                f"{forecast.rate_per_hour:+.2%}/h (R²={forecast.r2:.3f}); full in "
                f"{hours:.1f} h at this rate, at {limit_in_unit:,.0f} {resource.unit}"
            ),
            subject=subject,
            payload=payload,
        )

        return Finding(
            id=uuid5(
                _EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:{resource.name}:{member}"
            ),
            agent=self.codename,
            kind=FindingKind.RISK,
            title=(
                f"{resource.name} on {resource.label} {member} reaches full in "
                f"{hours:.1f} h at the current rate"
            ),
            severity=FORECAST_SEVERITY,
            # R², because it is the one number here that says how much the
            # projection can be believed, and a reader of `confidence` should
            # get exactly that rather than a second scale invented beside it.
            confidence=_bounded(forecast.r2),
            detected_at=datetime.now(tz=UTC),
            # The window that was READ, not the one that was handed over. A
            # Finding claiming a five-minute window for a fit over a day would
            # misstate its own evidence.
            window_start=_lookback_start(ctx),
            window_end=ctx.window_end,
            subject=subject,
            evidence=[evidence],
            tags=[
                f"resource:{resource.name}",
                f"{resource.label}:{member}",
                f"horizon-hours:{HORIZON_HOURS:g}",
                "confidence:fit-r2",
                "projects-to:full",
            ],
        )


def _lookback_start(ctx: AgentContext) -> datetime:
    """Where Moira's window begins: `LOOKBACK_HOURS` before the incident's end.

    Never later than the incident's own start, so a caller that handed over a
    window longer than the lookback is not silently given less than it asked.
    """
    own = ctx.window_end - timedelta(hours=LOOKBACK_HOURS)
    return min(own, ctx.window_start)


def _parse(raw: object, label: str) -> dict[str, dict[float, float]]:
    """Prometheus range response to {member: {timestamp: value}}."""
    out: dict[str, dict[float, float]] = {}
    result = raw.get("result", []) if isinstance(raw, dict) else []
    for entry in result:
        member = entry.get("metric", {}).get(label)
        if not member:
            continue
        out[member] = {
            round(float(at)): float(value)
            for at, value in entry.get("values", [])
            if math.isfinite(float(value))
        }
    return out


def _ratio_series(
    used: dict[float, float], total: dict[float, float]
) -> tuple[list[MetricSample], float]:
    """used / total at every instant both reported, and the total at the end.

    Instants where only one side reported are dropped rather than filled: a
    ratio built from a stale total is a ratio against the wrong disk.
    """
    stamps = sorted(set(used) & set(total))
    samples = [
        MetricSample(at=datetime.fromtimestamp(at, tz=UTC), value=used[at] / total[at])
        for at in stamps
        if total[at] > 0.0
    ]
    limit = total[stamps[-1]] if stamps else 0.0
    return samples, limit


def _bounded(value: float) -> float:
    return min(max(value, 0.0), 1.0)
