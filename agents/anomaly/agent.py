"""Argus - detects metric anomalies against calibrated, measured thresholds.

WHAT THIS DOES, AND WHAT IT DOES NOT
------------------------------------
It separates a fault from a clean baseline. **That is the whole of it.**

It does not say what broke, and it cannot. Measured across all five simulator
scenarios, several metrics cross their thresholds during one incident and every
crossing is correct: `latency` reads 23.85 during `bad_deploy_5xx` because a bad
deploy really does raise latency, and `cpu` reads 8.93 during `noisy_neighbor`
because a noisy neighbour really does saturate a node. So **one incident
produces several Findings and none of them is a diagnosis.** Deciding which
crossing is the cause is correlation, and correlation is Zeus's and Delphi's
work. Anything that reads a single Finding from here as a root cause is reading
it wrong.

Detection is statistical only. No LLM is involved and none is needed:
`Finding.rationale` is optional, so a templated title plus real Evidence is a
complete claim. Delphi arrives in Phase 2 to narrate `rationale`.

THE METHOD, AND WHERE ITS NUMBERS CAME FROM
-------------------------------------------
Peer-relative robust z: at each instant a member is compared against the median
and MAD of its peers, so the diurnal cycle - which is common-mode across peers -
cancels without needing a window or a period estimate. `calibration.py` holds
every parameter and the measurement behind it; `docs/argus-threshold-matrix.md`
is the derivation.

A crossing must be **sustained** for `SUSTAIN_SAMPLES` consecutive instants. One
instant over the line is a scrape, not an incident.

REFUSALS ARE REPORTED, NOT SILENT
---------------------------------
A metric with no calibrated threshold, or no measured scale floor, is not
scanned - and the run says so. It raises `AgentDegraded` carrying every anomaly
it did find as `partial`, so the scan's results survive and the runtime builds
the DEGRADED Finding. Agents never build one themselves: every agent has to
report inability the same way or the dashboard cannot tell two of them apart.

An agent that quietly skipped a metric would be indistinguishable from one that
looked and found nothing, which is the distinction `AgentOutcome` exists to
preserve.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.anomaly.calibration import (
    SUSTAIN_SAMPLES,
    InsufficientPeersError,
    MetricNotCalibratedError,
    NonFiniteSampleError,
    PartialPeerCoverageError,
    ScaleFloorNotMeasuredError,
    floor_for,
    peer_z,
    threshold_for,
)
from core.contracts.evidence import (
    BaselineEstimator,
    Evidence,
    EvidenceSource,
    MetricSample,
    MetricWindowPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity

#: Namespace for deterministic evidence ids, so the same observation carries the
#: same id on every attempt - the reason `BaseAgent.finding_id` exists.
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/argus/evidence")

#: Seconds between samples requested from Prometheus.
STEP_SECONDS = 1

#: Severity is the same for every detection, on purpose.
#:
#: Ranking incidents means knowing which crossing is the cause, and that is the
#: judgement this agent explicitly does not make. The magnitude is not lost - it
#: is on the Evidence as `deviation_sigma` - but putting it in `severity` would
#: assert that a metric 100x over its threshold matters more than one 2x over,
#: which depends entirely on which fault produced it.
DETECTION_SEVERITY = Severity.MEDIUM


@dataclass(frozen=True)
class SeriesSpec:
    """How to fetch one calibrated metric, and what its members are.

    `label` is the peer axis: the label whose distinct values are the peers
    compared against each other. Getting it wrong silently compares the wrong
    group, which is why `tests/unit/test_argus_detection.py` asserts every
    calibrated metric has a spec and every spec names a calibrated metric.
    """

    query: str
    label: str
    unit: str
    resource_kind: str


#: Every metric Argus knows how to fetch. Calibration decides whether it is
#: actually scanned - a spec here without a threshold produces a DEGRADED
#: Finding rather than a scan.
SERIES: dict[str, SeriesSpec] = {
    "memory": SeriesSpec(
        query="pantheon_pod_memory_working_set_bytes",
        label="pod",
        unit="bytes",
        resource_kind="pod",
    ),
    "cpu": SeriesSpec(
        query="pantheon_pod_cpu_cores",
        label="pod",
        unit="cores",
        resource_kind="pod",
    ),
    "latency": SeriesSpec(
        query="pantheon_http_request_duration_seconds",
        label="pod",
        unit="seconds",
        resource_kind="pod",
    ),
    "disk_ratio": SeriesSpec(
        query="pantheon_node_disk_used_bytes / pantheon_node_disk_total_bytes",
        label="node",
        unit="ratio",
        resource_kind="node",
    ),
    "ci_ratio": SeriesSpec(
        query="pantheon_ci_pipeline_failure_ratio",
        label="service",
        unit="ratio",
        resource_kind="service",
    ),
    "error_ratio": SeriesSpec(
        query=(
            'sum by (service) (rate(pantheon_http_requests_total{status="500"}[10s]))'
            " / (sum by (service) (rate(pantheon_http_requests_total[10s])) > 0)"
        ),
        label="service",
        unit="ratio",
        resource_kind="service",
    ),
}


@dataclass(slots=True)
class _Reading:
    """One instant's peer comparison for one member."""

    at: float
    value: float
    z: float
    centre: float
    scale: float
    floor_engaged: bool


class Argus(BaseAgent):
    """The first real agent, and the template the other nine follow."""

    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Report every metric whose peer comparison crossed its threshold.

        Returns `[]` when the window is clean - that is a result, not a failure.
        Raises `AgentDegraded` only when Prometheus itself could not be reached;
        a single metric failing produces a DEGRADED Finding for that metric and
        leaves the rest of the scan intact.
        """
        findings: list[Finding] = []
        refusals: list[str] = []
        reached_prometheus = False

        for metric in sorted(SERIES):
            spec = SERIES[metric]
            try:
                threshold = threshold_for(metric).threshold
                floor = floor_for(metric)
            except (MetricNotCalibratedError, ScaleFloorNotMeasuredError) as refusal:
                refusals.append(f"{metric}: {refusal}")
                continue

            try:
                raw = await ctx.tools.call(
                    "prometheus.query_range",
                    query=spec.query,
                    start=ctx.window_start.timestamp(),
                    end=ctx.window_end.timestamp(),
                    step=f"{STEP_SECONDS}s",
                )
            except Exception as error:
                refusals.append(f"{metric}: query failed: {error}")
                continue
            reached_prometheus = True

            by_member = _parse(raw, spec.label)
            if len(by_member) < 2:
                refusals.append(f"{metric}: only {len(by_member)} series returned")
                continue

            readings, usable, refused = _compare(by_member, floor)
            if not usable:
                refusals.append(
                    f"{metric}: no instant had complete peer coverage ({refused} refused)"
                )
                continue

            for member, series in sorted(readings.items()):
                run = _sustained_run(series, threshold)
                if run is None:
                    continue
                findings.append(
                    self._anomaly(ctx, metric, spec, member, series, run, usable, threshold)
                )

        if not reached_prometheus:
            raise AgentDegraded(
                "no metric could be fetched from Prometheus, so nothing was scanned. "
                "This is an inability to look, not an absence of anomalies.",
                retryable=True,
                partial=findings,
            )
        if refusals:
            raise AgentDegraded(
                f"{len(refusals)} of {len(SERIES)} metrics were not scanned, so this run "
                "is partial and a quiet result for them means nothing: " + "; ".join(refusals),
                retryable=False,
                partial=findings,
            )
        return findings

    # -- finding construction ---------------------------------------------

    def _anomaly(
        self,
        ctx: AgentContext,
        metric: str,
        spec: SeriesSpec,
        member: str,
        series: list[_Reading],
        run: tuple[int, int],
        usable: int,
        threshold: float,
    ) -> Finding:
        start, end = run
        peak = max(series[start:end], key=lambda r: abs(r.z))
        crossings = sum(1 for r in series if abs(r.z) > threshold)

        subject = ResourceRef(kind=spec.resource_kind, name=member)
        payload = MetricWindowPayload(
            metric=spec.query,
            unit=spec.unit,
            samples=[
                MetricSample(at=datetime.fromtimestamp(r.at, tz=UTC), value=r.value)
                for r in series[start:end]
            ],
            estimator=BaselineEstimator.MEDIAN_MAD,
            baseline_centre=peak.centre,
            baseline_scale=peak.scale,
            deviation_sigma=peak.z,
            scale_floor_engaged=peak.floor_engaged,
            window_seconds=int(ctx.window_end.timestamp() - ctx.window_start.timestamp()),
        )
        evidence = Evidence(
            id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:{metric}:{member}"),
            source=EvidenceSource(
                connector="prometheus",
                query=spec.query,
                collected_at=datetime.now(tz=UTC),
            ),
            observed_at=datetime.fromtimestamp(peak.at, tz=UTC),
            summary=(
                f"{spec.label}={member} reached z={peak.z:+.2f} against its peers "
                f"(threshold {threshold}), sustained {end - start} samples"
                + (" - SCALE FLOOR ENGAGED" if peak.floor_engaged else "")
            ),
            subject=subject,
            payload=payload,
        )

        # `rationale` stays None. Argus states what it observed; saying why the
        # Evidence supports a conclusion is Delphi's job, and a templated
        # sentence here would read like an explanation nobody produced.
        return Finding(
            id=uuid5(_EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:{metric}:{member}"),
            agent=self.codename,
            kind=FindingKind.ANOMALY,
            title=f"{metric} on {spec.label} {member} crossed its calibrated threshold",
            severity=DETECTION_SEVERITY,
            confidence=_confidence(crossings, usable),
            detected_at=datetime.now(tz=UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=subject,
            evidence=[evidence],
            tags=[
                f"metric:{metric}",
                f"{spec.label}:{member}",
                f"threshold:{threshold}",
                # N is on the Finding because the confidence has no resolution
                # finer than 1/N, and a reader cannot tell that from the number.
                f"n:{usable}",
                "confidence:coverage-fraction",
                *(["floor-engaged"] if peak.floor_engaged else []),
            ],
        )


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


def _compare(
    by_member: dict[str, dict[float, float]], floor: float
) -> tuple[dict[str, list[_Reading]], int, int]:
    """Peer-compare every instant every member reported.

    Instants without complete coverage are refused rather than compared on
    whoever arrived - see `peer_z`. The refused count is returned so a mostly
    uncovered window is visible instead of looking like a quiet one.
    """
    peers = sorted(by_member)
    stamps = sorted(set.intersection(*(set(v) for v in by_member.values())))
    readings: dict[str, list[_Reading]] = {peer: [] for peer in peers}
    usable = 0
    refused = 0

    for at in stamps:
        samples = {peer: by_member[peer][at] for peer in peers if at in by_member[peer]}
        try:
            comparison = peer_z(peers, samples, scale_floor=floor)
        except (InsufficientPeersError, PartialPeerCoverageError, NonFiniteSampleError):
            refused += 1
            continue
        usable += 1
        for peer in peers:
            readings[peer].append(
                _Reading(
                    at=at,
                    value=samples[peer],
                    z=comparison.z[peer],
                    centre=comparison.centre,
                    scale=comparison.scale,
                    floor_engaged=comparison.floor_engaged,
                )
            )
    return readings, usable, refused


def _sustained_run(series: list[_Reading], threshold: float) -> tuple[int, int] | None:
    """The longest run of consecutive instants above threshold, if long enough.

    One instant over the line is a scrape. `SUSTAIN_SAMPLES` is derived in
    `calibration.py` from how long a real fault holds.
    """
    best: tuple[int, int] | None = None
    start: int | None = None
    for index, reading in enumerate(series):
        if abs(reading.z) > threshold:
            start = index if start is None else start
            length = index - start + 1
            if length >= SUSTAIN_SAMPLES and (best is None or length > best[1] - best[0]):
                best = (start, index + 1)
        else:
            start = None
    return best


def _confidence(crossings: int, usable: int) -> float:
    """The fraction of usable instants that crossed, and nothing more.

    **Not a calibrated probability.** It is a coverage fraction: a fault holding
    for half the window reads 0.5, and that is all it asserts. Calling it a
    probability of being a true positive would claim a calibration nobody has
    measured - the false-positive bound in the matrix is a rate per instant, not
    a per-Finding likelihood.

    Its resolution is 1/`usable` by construction, which is why `usable` is
    carried on the Finding as `n:`. A confidence of 0.333 from three instants and
    one from three thousand are different claims, and the number alone cannot
    tell them apart.
    """
    if usable <= 0:
        return 0.0
    return min(1.0, crossings / usable)
