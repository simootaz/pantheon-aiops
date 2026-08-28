"""Collapses agent Findings into a single Verdict.

THE VERDICT PROPOSES NO HYPOTHESES, AND THAT IS THE HONEST OUTPUT
------------------------------------------------------------------
`Verdict.hypotheses` comes back **empty**, deliberately. The contract already
says what that means:

    Empty means no explanation was reached, which is a legitimate outcome and
    must not be dressed up as one.

Argus detects. It reports that a series crossed a threshold its peers did not,
and it says so several times per incident because several metrics move - during
`bad_deploy_5xx` both `error_ratio` and `latency` cross, and both are correct.
Lethe now runs on the same alert and reports what appeared in the logs, so a
single incident produces findings from two agents about the same window.

Choosing between them is a root-cause judgement, and nothing in this repository
makes one yet. **Delphi is no longer the blocker** - it landed, with resolution,
probing and a fallback chain. What is still missing is the step that decides two
findings describe one event and ranks the candidates, and that is the same gap
`core/contracts/finding.py` names for cross-agent correlation ids. It should be
built once.

So a Verdict here is **an aggregation of what the agents found, not a
diagnosis.**
Synthesising a hypothesis from a detector's output would mean inventing the
step between "this moved" and "this is why", and inventing it in a field that
`simulator/scenarios/*.yaml` provides ground truth for - so the invention would
then be scored as though it were reasoning.

`confidence` is 0.0 for the same reason: it is defined as confidence in the
leading hypothesis, and there is no leading hypothesis.

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
from core.contracts.verdict import Verdict


def aggregate(investigation_id: UUID, findings: list[Finding], steps: list[PlanStep]) -> Verdict:
    """One Verdict from what the agents returned and what actually ran."""
    anomalies = [f for f in findings if f.kind is FindingKind.ANOMALY]
    degraded = [f for f in findings if f.kind is FindingKind.DEGRADED]

    return Verdict(
        id=uuid4(),
        investigation_id=investigation_id,
        summary=_summary(anomalies, degraded, steps),
        hypotheses=[],
        confidence=0.0,
        contributing_findings=findings,
        recommended_actions=[],
        decided_at=datetime.now(UTC),
        steps=steps,
    )


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
