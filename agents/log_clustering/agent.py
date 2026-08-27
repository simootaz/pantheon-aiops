"""Lethe - reduces a log window to templates and reports the ones that are new.

WHAT THIS DOES, AND WHAT IT DOES NOT
------------------------------------
It reports **log patterns whose absence from a reference window is surprising**,
and the exception traces in the window. That is the whole of it.

It cannot detect a fault that amplifies a pattern the reference already has, and
that is not a gap to be filled later by tuning - it is measured, and it is most
faults. `bad_deploy_5xx` introduces no new template: the simulator emits a 500 in
normal traffic, so `request failed` is in every baseline window and a bad deploy
multiplies it rather than introducing it. **Lethe is blind to that scenario.**

A rate-increase test was written and deleted. On two CLEAN baseline windows it
reported surges at 1.29x while the five fault scenarios topped out at 1.31x -
1.54x, so a fault was not distinguishable from no fault. Log volume follows the
diurnal curve, and comparing a window against an earlier window measures the
time of day. Making that work needs seasonality cancelled by a **peer axis** -
this pod against its peers at the same instant, the way `agents/anomaly` does -
and that is not built. See docs/lethe-predictions/02-surprise-and-surge.md.

Anything reading a Finding from here as a root cause is reading it wrong, for
the same reason as Argus: a new log pattern is a fact about the logs, and
deciding which fact is the cause is Zeus's and Delphi's work.

THE REFERENCE WINDOW
----------------------
Novelty needs something to be novel against. Lethe uses the window of equal
length immediately preceding `ctx.window_start`.

That choice has a failure mode worth naming rather than discovering: if the
fault began before the reference window, the reference contains it, and the
pattern is not novel. Lethe will then report nothing and look like a clean run.
`reference_covers_fault` is not knowable from inside the agent, so the window is
reported on every Finding and the limitation is stated here.

Detection is statistical only. No LLM is involved: `Finding.rationale` is
optional, so a templated title plus real Evidence is a complete claim.

REFUSALS ARE REPORTED, NOT SILENT
---------------------------------
A window too small to template, a reference that came back empty, or a Loki that
could not be reached all raise `AgentDegraded` carrying whatever was found as
`partial`. The runtime builds the DEGRADED Finding; agents never build one
themselves, or the dashboard cannot tell two of them apart.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.log_clustering.templates import (
    SIGNIFICANCE,
    Clustering,
    StackTrace,
    Template,
    compare,
    novel,
    stack_traces,
)
from agents.log_clustering.tools import attach
from core.config import get_settings
from core.contracts.evidence import Evidence, EvidenceSource, LogClusterPayload, ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity

#: Namespace for deterministic evidence ids, so the same observation carries the
#: same id on every attempt - the reason `BaseAgent.finding_id` exists.
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/lethe/evidence")

#: The LogQL selector, from config. Not a literal here: the job name has one
#: home, and an agent that spelled it out could not be pointed at a different
#: deployment without an edit.
SELECTOR = get_settings().loki.selector

#: Lines requested per window. The Loki connector caps at 5000 and does not page,
#: so a quiet incident inside a noisy window can be missed entirely - measured as
#: an open limitation, not a solved one.
WINDOW_LIMIT = 5000

#: Below this many parsed lines a window cannot be templated: most groups fall
#: under `MIN_GROUP_FOR_VARIABILITY` and come back shape-only, and a comparison
#: between two sets of shape-only templates is a comparison of window sizes.
#:
#: Measured: the template set is disjoint from its converged form below ~1000
#: lines and identical at 1000. Set at the low end of that step rather than the
#: high, because refusing a window that would have worked is the cheaper error.
MIN_LINES_TO_TEMPLATE = 500

#: Severity is the same for every detection, on purpose - the same argument as
#: Argus. Ranking means knowing which pattern is the cause, and that is the
#: judgement this agent explicitly does not make.
DETECTION_SEVERITY = Severity.MEDIUM


def _short(text: str, limit: int = 80) -> str:
    """Enough of a template to tell two findings apart in a list."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Lethe(BaseAgent):
    """The log side of detection. Templates a window, reports what is new in it."""

    domain = "log_clustering"

    def bind_tools(self, tools: Any) -> None:
        """Attach the Loki connector to the toolset the runtime built.

        The runtime owns the toolset - `BaseAgent.run` constructs it from the
        manifest and replaces whatever a caller put on the context.
        """
        attach(tools)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Report novel log patterns and exception traces in the window.

        Returns `[]` when nothing is new - that is a result, not a failure.
        Raises `AgentDegraded` when the window could not be read or could not be
        templated, carrying whatever was found so a partial scan survives.
        """
        span = ctx.window_end.timestamp() - ctx.window_start.timestamp()
        if span <= 0:
            raise AgentDegraded(
                f"the window is {span:.0f}s long, so there is nothing to read. "
                "A zero-length window is a caller error, not an empty result.",
                partial=[],
                retryable=False,
            )

        started, ended = ctx.window_start.timestamp(), ctx.window_end.timestamp()
        incident_lines = await self._read(ctx, started, ended)
        reference_lines = await self._read(ctx, started - span, started)

        traces = stack_traces(incident_lines)
        findings: list[Finding] = [self._trace_finding(ctx, trace) for trace in traces]

        if len(incident_lines) < MIN_LINES_TO_TEMPLATE:
            raise AgentDegraded(
                f"the window held {len(incident_lines)} lines, below the "
                f"{MIN_LINES_TO_TEMPLATE} needed to template one. Under that, most "
                "groups fall below the variability floor and come back as shapes "
                "with no content, so a comparison would be measuring window size. "
                "Stack traces were still extracted and are attached.",
                partial=findings,
                retryable=False,
            )

        if len(reference_lines) < MIN_LINES_TO_TEMPLATE:
            raise AgentDegraded(
                f"the reference window held {len(reference_lines)} lines, below the "
                f"{MIN_LINES_TO_TEMPLATE} needed to template one. Everything in the "
                "incident window would look novel against it, which is a statement "
                "about the reference and not about the incident.",
                partial=findings,
                retryable=False,
            )

        incident, reference = compare(incident_lines, reference_lines)
        for template in novel(incident, reference):
            findings.append(self._novel_finding(ctx, template, incident, reference))

        return findings

    async def _read(self, ctx: AgentContext, start: float, end: float) -> list[str]:
        """One window of lines, in EMISSION ORDER.

        Sorting is not tidiness. `templates.py` decides whether a field is a
        clock by whether it moves one way through the corpus, and Loki returns
        several streams concatenated - in which arrangement a real clock runs
        forward inside a stream and jumps back at every boundary. Unsorted, the
        rule finds nothing and every template carries a timestamp.

        The nanosecond stamp is Loki's own, so this is emission order stated by
        the source rather than inferred from the text.
        """
        try:
            raw = await ctx.tools.call(
                "loki.query_range",
                query=SELECTOR,
                start=str(int(start * 1_000_000_000)),
                end=str(int(end * 1_000_000_000)),
                limit=WINDOW_LIMIT,
                direction="backward",
            )
        except Exception as error:
            raise AgentDegraded(
                f"loki could not be read for {start:.0f}-{end:.0f}: {error}. Nothing "
                "was scanned, which is different from finding nothing.",
                partial=[],
                retryable=True,
            ) from error

        entries = [
            (int(entry[0]), str(entry[1]))
            for stream in raw.get("result", [])
            for entry in stream.get("values", [])
        ]
        entries.sort()
        return [line for _stamp, line in entries]

    def _novel_finding(
        self,
        ctx: AgentContext,
        template: Template,
        incident: Clustering,
        reference: Clustering,
    ) -> Finding:
        """One template whose absence from the reference was surprising."""
        expected = (template.count / max(incident.lines_seen, 1)) * reference.lines_seen
        # P(absent | this rate). `novelty` on the payload is its complement, so
        # 1.0 means "could not plausibly have been missed" rather than a label.
        chance_of_absence = math.exp(-expected)

        subject = ResourceRef(kind="log_stream", name=SELECTOR)
        payload = LogClusterPayload(
            template=template.rendered,
            sample_lines=list(template.examples),
            occurrences=template.count,
            first_seen=ctx.window_start,
            last_seen=ctx.window_end,
            novelty=min(1.0, max(0.0, 1.0 - chance_of_absence)),
        )
        evidence = Evidence(
            id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:novel:{template.signature}"),
            source=EvidenceSource(
                connector="loki",
                query=SELECTOR,
                collected_at=datetime.now(tz=UTC),
            ),
            observed_at=ctx.window_end,
            summary=(
                f"{template.count} lines matching a template absent from the "
                f"previous window; {expected:.1f} were expected there if the rate "
                f"had held (p={chance_of_absence:.4f} < {SIGNIFICANCE})"
            ),
            subject=subject,
            payload=payload,
        )

        # `rationale` stays None. Lethe states what it observed; saying why the
        # Evidence supports a conclusion is Delphi's job.
        return Finding(
            id=uuid5(
                _EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:novel:{template.signature}"
            ),
            agent=self.codename,
            kind=FindingKind.ANOMALY,
            # The template is in the title, truncated. A title identical for
            # every novel finding makes a list of them unreadable, and the
            # reader would have to open each one to tell them apart.
            title=f"new log pattern: {_short(template.rendered)}",
            severity=DETECTION_SEVERITY,
            confidence=min(1.0, max(0.0, 1.0 - chance_of_absence)),
            detected_at=datetime.now(tz=UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=subject,
            evidence=[evidence],
            tags=[
                "novel-template",
                f"occurrences:{template.count}",
                f"reference-lines:{reference.lines_seen}",
                f"incident-lines:{incident.lines_seen}",
                # On the Finding because the confidence is a tail probability and
                # a reader cannot tell that from the number alone.
                "confidence:absence-surprise",
            ],
        )

    def _trace_finding(self, ctx: AgentContext, trace: StackTrace) -> Finding:
        """One exception, however many times it was thrown.

        Grouped with line numbers and pointers masked, so the same fault at two
        line numbers is one trace. Without that, forty throws of one bug were
        reported as forty separate faults.
        """
        subject = ResourceRef(kind="log_stream", name=SELECTOR)
        payload = LogClusterPayload(
            template=trace.header,
            sample_lines=list(trace.frames),
            occurrences=trace.count,
            first_seen=ctx.window_start,
            last_seen=ctx.window_end,
            # No novelty claim: this is not compared against a reference window.
            # A number here would be an assertion nothing measured.
            novelty=None,
        )
        evidence = Evidence(
            id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:trace:{trace.signature}"),
            source=EvidenceSource(
                connector="loki", query=SELECTOR, collected_at=datetime.now(tz=UTC)
            ),
            observed_at=ctx.window_end,
            summary=f"{trace.header} - thrown {trace.count} times, {len(trace.frames)} frames",
            subject=subject,
            payload=payload,
        )
        return Finding(
            id=uuid5(
                _EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:trace:{trace.signature}"
            ),
            agent=self.codename,
            kind=FindingKind.OBSERVATION,
            title=f"{_short(trace.header)} - thrown {trace.count} times",
            severity=DETECTION_SEVERITY,
            # An extracted trace is not an inference - the lines are either
            # there or they are not, so there is nothing to be uncertain about.
            confidence=1.0,
            detected_at=datetime.now(tz=UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=subject,
            evidence=[evidence],
            tags=["stack-trace", f"throws:{trace.count}", "confidence:extraction-is-not-inference"],
        )
