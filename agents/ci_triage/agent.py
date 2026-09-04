"""Hephaestus - triages a failed CI run, and separates flake from unknown.

WHAT THIS REPORTS
-------------------
For every job that failed at one commit: whether the same job also PASSED at
that commit. If it did, the job is flaky by definition. If it did not, nothing
here can say why it failed, and that is reported as `UNKNOWN` rather than
guessed at.

Most CI failures are the second case. A triage agent that labelled every first
failure would be right about half of them and trusted for neither.

NO THRESHOLD, SO NO PREDICTIONS RECORD
----------------------------------------
`docs/argus-predictions/` and `docs/lethe-predictions/` exist because those
agents rest on numbers that had to be chosen, and a number chosen after looking
at the data is a description of that data.

Nothing here is a number. "The same job at the same commit finished two
different ways" is exact, and the only bound in the file is a quota limit on how
many runs to read - which changes how much is looked at, never what is
concluded.

WHY EVERY RUN IS FETCHED AT THE COMMIT
----------------------------------------
The run that triggered this is one attempt. Flake detection needs the others,
and GitHub records a rerun as a separate run at the same `head_sha`. Reading
only the triggering run makes every flake look like a plain failure - the agent
would be structurally incapable of its one real capability.

No LLM is involved. `Finding.rationale` is optional, so a templated title and
real Evidence are a complete claim - the same choice as Argus, Lethe and Aegis.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.ci_triage.tools import attach
from agents.ci_triage.triage import Triage, Verdict, classify, outcomes_from
from core.contracts.evidence import (
    Evidence,
    EvidenceSource,
    PipelineRunPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity

_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/hephaestus/evidence")

#: How many runs at one commit to read jobs for.
#:
#: A quota bound, not a detection threshold: it changes how much is looked at
#: and never what is concluded. Ten reruns of one commit is already an unusual
#: day, and each costs one request.
MAX_RUNS = 10

#: The same for every triage, deliberately - the same argument as Argus and
#: Lethe. Ranking would mean knowing which failing job matters most, and that is
#: a judgement about the codebase this agent does not make.
TRIAGE_SEVERITY = Severity.MEDIUM


class Hephaestus(BaseAgent):
    """The CI side of triage. Says which failures are non-deterministic."""

    domain = "ci_triage"

    def bind_tools(self, tools: Any) -> None:
        attach(tools)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Report every job that failed at this commit, and what can be said.

        Returns `[]` when nothing failed - a result, not a failure. Raises
        `AgentDegraded` when the run cannot be read at all, because a triage
        that could not look and a triage that found nothing are different facts.
        """
        repository = str(ctx.params.get("repository", ""))
        run_id = ctx.params.get("run")
        if not repository or not run_id:
            raise AgentDegraded(
                "no CI run was named. Hephaestus reads `repository` and `run` off "
                "ctx.params - a triage with no run is not an empty result.",
                partial=[],
                retryable=False,
            )

        run = await ctx.tools.call("github.actions_run", repository=repository, run=run_id)
        head_sha = str(run.get("head_sha") or "")
        if not head_sha:
            raise AgentDegraded(
                f"run {run_id} names no head_sha, so its reruns cannot be found. "
                "Without them every flake reads as a plain failure.",
                partial=[],
                retryable=False,
            )

        listing = await ctx.tools.call(
            "github.workflow_runs", repository=repository, head_sha=head_sha
        )
        runs = _runs_of(listing)[:MAX_RUNS]

        jobs_by_run: dict[int, list[dict[str, Any]]] = {}
        for one in runs:
            identifier = one.get("id")
            if not isinstance(identifier, int):
                continue
            answer = await ctx.tools.call("github.jobs", repository=repository, run=identifier)
            jobs_by_run[identifier] = _jobs_of(answer)

        triaged = classify(outcomes_from(runs, jobs_by_run))
        return [
            self._finding(ctx, triage, repository, head_sha, index)
            for index, triage in enumerate(triaged)
        ]

    def _finding(
        self,
        ctx: AgentContext,
        triage: Triage,
        repository: str,
        head_sha: str,
        index: int,
    ) -> Finding:
        subject = ResourceRef(kind="pipeline", name=f"{repository}#{triage.job}")
        headline = (
            f"{triage.job} is flaky at {head_sha[:7]}"
            if triage.flaky
            else f"{triage.job} failed at {head_sha[:7]} and nothing here says why"
        )
        return Finding(
            id=ctx.investigation_id,
            agent=self.codename,
            kind=FindingKind.OBSERVATION,
            title=headline,
            severity=TRIAGE_SEVERITY,
            # 1.0 for a flake: it is read off two recorded outcomes, not
            # inferred from them. Lower for UNKNOWN, which is a statement that
            # the evidence supports nothing - and a confident "I do not know"
            # would be a strange thing to assert at full strength.
            confidence=1.0 if triage.verdict is Verdict.FLAKE else 0.5,
            detected_at=ctx.window_end,
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=subject,
            evidence=[
                Evidence(
                    id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:{index}"),
                    source=EvidenceSource(connector="github", query=f"runs?head_sha={head_sha}"),
                    observed_at=ctx.window_end,
                    summary=triage.why,
                    subject=subject,
                    payload=PipelineRunPayload(
                        pipeline_id=str(triage.attempts[0].run_id) if triage.attempts else "",
                        project=repository,
                        ref=head_sha,
                        status="failed",
                        failed_jobs=[triage.job],
                        commit_sha=head_sha,
                    ),
                )
            ],
            tags=["ci", triage.verdict.value],
        )


def _runs_of(listing: Any) -> list[dict[str, Any]]:
    """GitHub wraps the runs in `workflow_runs`. A bare list is accepted too, so
    a caller handing back an already-unwrapped answer is not a crash."""
    if isinstance(listing, dict):
        runs = listing.get("workflow_runs")
        return [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
    return [run for run in listing if isinstance(run, dict)] if isinstance(listing, list) else []


def _jobs_of(answer: Any) -> list[dict[str, Any]]:
    if isinstance(answer, dict):
        jobs = answer.get("jobs")
        return [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []
    return [job for job in answer if isinstance(job, dict)] if isinstance(answer, list) else []
