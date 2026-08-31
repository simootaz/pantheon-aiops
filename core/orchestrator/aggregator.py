"""Collapses agent Findings into a single Verdict.

THE VERDICT PROPOSES ONLY WHAT A SIGNAL ENTITLES IT TO
-------------------------------------------------------
`Verdict.hypotheses` was empty for two phases, deliberately, because nothing
could turn "this moved" into "this is why" without inventing the step.

`core/orchestrator/hypotheses.py` is that step now, and it is narrow on purpose:
a hypothesis is proposed only from a signal whose metric *is* the thing the
category describes - resident memory for a leak, used-over-total for disk, the
pipeline failure ratio for a flaky test. Errors, latency and CPU corroborate and
name nothing, so `bad_deploy_5xx` and `noisy_neighbor` come back UNKNOWN with
their evidence attached.

That is the honest result rather than a gap: nothing here reports deployments,
and nothing knows which pods share a node. Both were committed as predicted
misses in `docs/zeus-predictions/01-hypothesis-ranking.md` before the ranker was
written, because the ground truth is in this repository and a mapping that named
all five would have been fitted to it.

`confidence` is still 0.0 whenever there is no LEADING hypothesis - none
proposed, or two tied. It is defined as confidence in the leading hypothesis,
and a tie is exactly where picking one would be the aggregator inventing a
judgement nothing made.

WHAT IT DOES CARRY
------------------
Every Finding, and every PlanStep with its real status - which is what lets a
reader tell "nobody found anything" from "nobody looked". `Verdict.partial`
derives from those steps, so a run where Argus degraded is visibly partial
without anyone remembering to set a flag.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from core.contracts.finding import Finding, FindingKind
from core.contracts.plan import PlanStep, StepStatus
from core.contracts.root_cause import RootCauseHypothesis
from core.contracts.verdict import Dissent, Verdict
from core.orchestrator.hypotheses import leading, rank


def aggregate(investigation_id: UUID, findings: list[Finding], steps: list[PlanStep]) -> Verdict:
    """One Verdict from what the agents returned and what actually ran."""
    anomalies = [f for f in findings if f.kind is FindingKind.ANOMALY]
    degraded = [f for f in findings if f.kind is FindingKind.DEGRADED]

    hypotheses = rank(findings)
    front_runner = leading(hypotheses)

    return Verdict(
        id=uuid4(),
        investigation_id=investigation_id,
        summary=_summary(anomalies, degraded, steps),
        hypotheses=hypotheses,
        # The LEADING one's confidence, or zero. Not the best score in the list:
        # two hypotheses tied at 0.55 are a run that reached no conclusion, and
        # reporting 0.55 would present a coin flip as a finding.
        confidence=front_runner.confidence if front_runner is not None else 0.0,
        dissent=_dissent(hypotheses, front_runner, findings),
        contributing_findings=findings,
        recommended_actions=[],
        decided_at=datetime.now(UTC),
        steps=steps,
    )


def _dissent(
    hypotheses: list[RootCauseHypothesis],
    front_runner: RootCauseHypothesis | None,
    findings: list[Finding],
) -> list[Dissent]:
    """The candidates the leading hypothesis does not account for.

    Empty when nothing leads. Two tied candidates are a run that reached no
    conclusion, not a majority with objectors - and calling one of two equals
    "the leader" would be the aggregator inventing the judgement `leading`
    deliberately refused to make.

    The agents are named. "Somebody disagreed" is not something anybody can
    follow up; "Argus's disk signal pointed elsewhere" is.
    """
    if front_runner is None:
        return []

    by_id = {finding.id: finding for finding in findings}
    return [
        Dissent(
            category=hypothesis.category,
            agents=sorted(
                {
                    by_id[finding_id].agent
                    for finding_id in hypothesis.supporting_finding_ids
                    if finding_id in by_id
                }
            ),
            finding_ids=list(hypothesis.supporting_finding_ids),
            confidence=hypothesis.confidence,
        )
        for hypothesis in hypotheses
        if hypothesis.id != front_runner.id
    ]


def _summary(anomalies: list[Finding], degraded: list[Finding], steps: list[PlanStep]) -> str:
    """One paragraph that says what was observed and refuses to say why.

    Written to be read by someone who will otherwise assume a verdict is a
    conclusion. The last sentence is not padding: it is the only thing standing
    between a list of detections and a reader treating the first one as a cause.
    """
    ran = [s for s in steps if s.status is not StepStatus.PENDING]
    complete = [s for s in ran if s.status is StepStatus.COMPLETE]
    agents = ", ".join(sorted({s.agent for s in ran})) or "no agent"

    if not ran:
        return (
            "No agent was dispatched, so nothing was looked at. This is not a finding "
            "that the cluster is healthy."
        )

    if not anomalies:
        if degraded or not complete:
            # NOT "no metric crossed". An agent that could not look has not
            # established that nothing moved, and saying so in the same sentence
            # as the failure is how a partial run reads as a clean one.
            return (
                f"{agents} could not complete in this window, so nothing was established "
                f"about the metrics it did not reach. {len(degraded)} step(s) reported "
                "being unable to look. This is a partial view, not a quiet cluster."
            )
        return (
            f"{agents} looked and found nothing in this window: no metric crossed its "
            "calibrated threshold. Every dispatched agent completed."
        )

    subjects = sorted({f.subject.name for f in anomalies if f.subject})
    metrics = sorted(
        {t.split(":", 1)[1] for f in anomalies for t in f.tags if t.startswith("metric:")}
    )
    partial = (
        f" {len(degraded)} step(s) could not complete, so this is a partial view."
        if degraded
        else ""
    )
    return (
        f"{agents} detected {len(anomalies)} threshold crossing(s) in this window, on "
        f"{', '.join(metrics) or 'unnamed metrics'} "
        f"across {', '.join(subjects) or 'unnamed subjects'}."
        f"{partial} These are detections, not an explanation: several metrics move during "
        "one incident and each crossing above is independently true. No hypothesis is "
        "offered because nothing here ranks candidate causes yet."
    )
