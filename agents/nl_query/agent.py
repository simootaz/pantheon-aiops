"""Hermes - turns a question into a connector query, and the result into an answer.

WHAT THIS DOES, AND WHAT IT DOES NOT
------------------------------------
Given a question in `ctx.params["question"]`, it asks a model which connector
query would answer it, **runs that query itself**, and asks the model to render
the result. It answers questions about what the connectors can see. It does not
diagnose, and it does not answer from the model's own knowledge.

This is the first agent that consults Delphi, so it is the first place ADR 0004's
central rule is exercised end to end: Hermes declares `ModelRequirements` and
never names a model.

THE MODEL PROPOSES; HERMES DECIDES
------------------------------------
A model asked to translate a question will always produce something. It never
says "I cannot". Every safeguard here follows from that:

* **The model chooses a tool and a query string. It does not choose the time
  range.** The window is `ctx.window_start`/`window_end` - a fact about the
  investigation, not something to be guessed at. A model that asked for thirty
  days would be answering a different question and reading a much larger one out
  of Prometheus.
* **A proposed tool outside the declared set is refused before it is called.**
  `tool_binding` would refuse it too, but at that point the error reads as a
  missing connector rather than as a model that invented a capability.
* **No data means no answer.** When the query comes back empty, Hermes reports
  that and does not consult the model again. Handing an empty result to a
  summariser and asking what it means is how "the service had no errors" becomes
  "the service is healthy" - a claim about the world from an absence of rows.

The raw result is attached as Evidence on every Finding, so the answer can be
checked against what the query actually returned rather than trusted.

REFUSALS ARE REPORTED, NOT SILENT
---------------------------------
No question, no usable plan after `MAX_PLAN_ATTEMPTS`, or a connector that
failed all raise `AgentDegraded`. The runtime builds the DEGRADED Finding.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.nl_query.tools import IMPLEMENTATIONS, attach
from core.contracts.evidence import (
    Evidence,
    EvidenceSource,
    LogClusterPayload,
    MetricSample,
    MetricWindowPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.llm import Capability, ModelRequirements, Tier
from core.llm.gateway import Delphi
from core.llm.provider import ProviderError

_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/hermes/evidence")

#: Two attempts, and the validation error is fed back into the second. One
#: attempt discards a plan that a single sentence would have fixed; unbounded
#: retries spend an agent's whole budget re-reading the same mistake.
MAX_PLAN_ATTEMPTS = 2

#: Lines a log question may read back. Well under the connector's own cap: a
#: question is not an investigation, and a five-thousand-line answer is not one
#: either.
LOG_LIMIT = 200

#: What Hermes needs from a model. Capabilities, never a model id - ADR 0004.
#: BALANCED rather than CHEAP: the planning step emits structured output that is
#: then executed, and a cheap model that formats it slightly wrong costs a whole
#: extra round trip to discover.
PLANNING_REQUIREMENTS = ModelRequirements(
    capabilities=[Capability.JSON_MODE],
    tier=Tier.BALANCED,
)

#: Summarising is prose over data already in hand, with no structure to get
#: wrong, so it asks for less.
ANSWER_REQUIREMENTS = ModelRequirements(tier=Tier.CHEAP)

_PLAN_SYSTEM = """You translate an operator's question into ONE connector query.

Reply with JSON only: {"tool": "<tool name>", "query": "<query string>", "why": "<one line>"}

Available tools:
- prometheus.query_instant - a PromQL expression evaluated at one instant.
- loki.query_range - a LogQL expression over a window.

Rules:
- Choose exactly one tool.
- Do NOT include a time range. The caller supplies the window.
- If the question cannot be answered by either tool, reply
  {"tool": null, "query": null, "why": "<what is missing>"}."""

_ANSWER_SYSTEM = """Answer the operator's question using ONLY the query result given.

State the numbers you were given. If the result does not answer the question,
say so. Never supply a value that is not in the result. Two sentences at most."""


@dataclass(frozen=True)
class _Plan:
    """A model's proposal, after validation."""

    tool: str
    query: str
    why: str


class Hermes(BaseAgent):
    """Natural language in, a connector query and a checkable answer out."""

    domain = "nl_query"

    def __init__(self, delphi: Delphi | None = None, **kwargs: Any) -> None:
        """`delphi` is injected so a test can hand over a recording fake.

        Defaulted lazily rather than here: building one reads configuration, and
        an agent that could not be constructed without a configured LLM could
        not be constructed in a unit test either.
        """
        super().__init__(**kwargs)
        self._delphi = delphi

    def bind_tools(self, tools: Any) -> None:
        attach(tools)

    @property
    def delphi(self) -> Delphi:
        if self._delphi is None:
            from core.llm.assembly import delphi_from_settings

            self._delphi = delphi_from_settings()
        return self._delphi

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Answer the question in `ctx.params`, or say why it cannot be answered."""
        question = str(ctx.params.get("question") or "").strip()
        if not question:
            raise AgentDegraded(
                "no question was given. Hermes answers a question; there is no "
                "default one, and inventing one would answer something nobody asked.",
                partial=[],
                retryable=False,
            )

        plan = await self._plan(ctx, question)
        result = await self._run(ctx, plan)

        if _is_empty(result):
            return [self._nothing_found(ctx, question, plan, result)]

        answer = await self._answer(ctx, question, plan, result)
        return [self._answered(ctx, question, plan, result, answer)]

    async def _plan(self, ctx: AgentContext, question: str) -> _Plan:
        """Ask which query answers this, and validate the reply before trusting it."""
        complaint = ""
        for attempt in range(MAX_PLAN_ATTEMPTS):
            prompt = f"Question: {question}"
            if complaint:
                prompt += f"\n\nYour previous reply was rejected: {complaint}"

            try:
                consultation = await self.delphi.consult(
                    PLANNING_REQUIREMENTS,
                    prompt=prompt,
                    requested_by=self.codename,
                    system=_PLAN_SYSTEM,
                    json_mode=True,
                )
            except Exception as failure:
                raise AgentDegraded(
                    f"the model could not be consulted: {failure}. No query was run.",
                    partial=[],
                    retryable=True,
                ) from failure

            # Appended even on the attempt that fails: a run that degraded still
            # spent the money, and a cost record that only survives success
            # cannot answer "what did this cost" for the runs anyone asks about.
            ctx.resolutions.append(consultation.record)

            complaint = _rejects(consultation.completion.text)
            if not complaint:
                body = json.loads(consultation.completion.text)
                return _Plan(
                    tool=str(body["tool"]),
                    query=str(body["query"]),
                    why=str(body.get("why", "")),
                )
            del attempt

        raise AgentDegraded(
            f"the model produced no usable query in {MAX_PLAN_ATTEMPTS} attempts. "
            f"Last problem: {complaint}. Nothing was run - a plan that does not "
            "validate is not executed on the chance that it works.",
            partial=[],
            retryable=False,
        )

    async def _run(self, ctx: AgentContext, plan: _Plan) -> Any:
        """Execute the plan, with the time range supplied by Hermes."""
        started, ended = ctx.window_start.timestamp(), ctx.window_end.timestamp()
        try:
            if plan.tool == "loki.query_range":
                return await ctx.tools.call(
                    plan.tool,
                    query=plan.query,
                    start=str(int(started * 1_000_000_000)),
                    end=str(int(ended * 1_000_000_000)),
                    limit=LOG_LIMIT,
                )
            return await ctx.tools.call(plan.tool, query=plan.query, time=ended)
        except (ProviderError, Exception) as failure:
            raise AgentDegraded(
                f"the query {plan.query!r} failed: {failure}. The question is "
                "unanswered, which is different from the answer being nothing.",
                partial=[],
                retryable=True,
            ) from failure

    async def _answer(self, ctx: AgentContext, question: str, plan: _Plan, result: Any) -> str:
        """Render the result. Only reached when there IS a result."""
        rendered = json.dumps(result)[:4000]
        try:
            consultation = await self.delphi.consult(
                ANSWER_REQUIREMENTS,
                prompt=f"Question: {question}\n\nQuery: {plan.query}\n\nResult:\n{rendered}",
                requested_by=self.codename,
                system=_ANSWER_SYSTEM,
            )
        except Exception as failure:
            raise AgentDegraded(
                f"the query ran but its result could not be summarised: {failure}",
                partial=[],
                retryable=True,
            ) from failure

        ctx.resolutions.append(consultation.record)
        return consultation.completion.text.strip()

    def _evidence(self, ctx: AgentContext, plan: _Plan, result: Any, tag: str) -> Evidence:
        """The raw result, so the answer can be checked rather than trusted."""
        connector = plan.tool.split(".", 1)[0]
        payload: LogClusterPayload | MetricWindowPayload
        if connector == "loki":
            payload = LogClusterPayload(
                template=plan.query,
                sample_lines=_log_lines(result)[:5],
                occurrences=len(_log_lines(result)),
                first_seen=ctx.window_start,
                last_seen=ctx.window_end,
                # Hermes compares nothing against anything, so it has no basis
                # for a novelty number and does not invent one.
                novelty=None,
            )
        else:
            payload = MetricWindowPayload(
                metric=plan.query,
                samples=_metric_samples(result, ctx.window_end),
                window_seconds=int(ctx.window_end.timestamp() - ctx.window_start.timestamp()),
            )

        return Evidence(
            id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:{tag}:{plan.query}"),
            source=EvidenceSource(
                connector=connector, query=plan.query, collected_at=datetime.now(tz=UTC)
            ),
            observed_at=ctx.window_end,
            summary=f"{plan.tool} ran {plan.query!r}: {plan.why or 'no reason given'}",
            subject=ResourceRef(kind="query", name=plan.tool),
            payload=payload,
        )

    def _answered(
        self, ctx: AgentContext, question: str, plan: _Plan, result: Any, answer: str
    ) -> Finding:
        return Finding(
            id=uuid5(_EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:answer:{question}"),
            agent=self.codename,
            kind=FindingKind.OBSERVATION,
            title=f"answered: {question[:70]}",
            severity=Severity.INFO,
            # An answer is exactly as good as the query behind it, and Hermes
            # has no way to score that. A number here would be the model's
            # self-assessment wearing a measurement's clothes.
            confidence=1.0,
            detected_at=datetime.now(tz=UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=ResourceRef(kind="query", name=plan.tool),
            evidence=[self._evidence(ctx, plan, result, "answer")],
            rationale=answer,
            tags=["nl-query", f"tool:{plan.tool}", "confidence:not-a-measurement"],
        )

    def _nothing_found(self, ctx: AgentContext, question: str, plan: _Plan, result: Any) -> Finding:
        """The query ran and returned nothing.

        Reported as a fact about the query, with no model consulted. Asking a
        summariser what an empty result means is how "no error rows" becomes
        "the service is healthy".
        """
        return Finding(
            id=uuid5(_EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}:empty:{question}"),
            agent=self.codename,
            kind=FindingKind.OBSERVATION,
            title=f"no data for: {question[:70]}",
            severity=Severity.INFO,
            confidence=1.0,
            detected_at=datetime.now(tz=UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=ResourceRef(kind="query", name=plan.tool),
            evidence=[self._evidence(ctx, plan, result, "empty")],
            rationale=(
                f"{plan.query!r} returned no data for this window. That is what the "
                "query found, and it is not a statement about whether anything is wrong."
            ),
            tags=["nl-query", "empty-result", f"tool:{plan.tool}"],
        )


def _rejects(text: str) -> str:
    """Why this reply is not a usable plan, or an empty string if it is.

    Every check is on the model's output, because that is the only untrusted
    input here. A plan is executed against real infrastructure, so it is
    validated before it is run rather than after it fails.
    """
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return "the reply was not JSON"

    if not isinstance(body, dict):
        return "the reply was JSON but not an object"

    tool, query = body.get("tool"), body.get("query")
    if tool is None:
        return f"the model said the question cannot be answered: {body.get('why', 'no reason')}"
    if tool not in IMPLEMENTATIONS:
        return f"{tool!r} is not one of {sorted(IMPLEMENTATIONS)}"
    if not isinstance(query, str) or not query.strip():
        return "no query string"
    return ""


def _is_empty(result: Any) -> bool:
    """Whether the connector returned nothing.

    Both connectors nest their rows under `result`, and both can answer with an
    empty one. `None` is included because a connector that returned nothing at
    all is also nothing - and treating it as data would put `null` in front of a
    summariser.
    """
    if result is None:
        return True
    if isinstance(result, dict):
        return not result.get("result")
    return not result


def _log_lines(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    return [
        str(entry[1])
        for stream in result.get("result", [])
        for entry in stream.get("values", [])
        if len(entry) > 1
    ]


def _metric_samples(result: Any, at: datetime) -> list[MetricSample]:
    """Prometheus instant vectors, as samples.

    Silently empty on an unexpected shape rather than raising: the raw result is
    on the Evidence either way, so a reader can see what came back even when
    this could not read it.
    """
    if not isinstance(result, dict):
        return []
    samples: list[MetricSample] = []
    for row in result.get("result", []):
        value = row.get("value")
        if not value or len(value) < 2:
            continue
        try:
            samples.append(MetricSample(at=at, value=float(value[1])))
        except (TypeError, ValueError):
            continue
    return samples
