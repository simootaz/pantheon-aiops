"""What Hermes runs, refuses and never claims - offline, with a scripted model.

No live model is called here. The interesting properties are all about what
Hermes does with what a model *says*, and a real one would make those tests
non-deterministic while proving nothing extra.

The security-shaped cases are the point. A model asked to translate a question
always produces something, so every assertion below is about Hermes refusing to
act on the parts of that something it has no reason to trust.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext, AgentDegraded
from agents._base.tool_binding import BoundTools, ToolNotDeclared
from agents.nl_query.agent import (
    MAX_PLAN_ATTEMPTS,
    Hermes,
    _is_empty,
    _log_lines,
    _metric_samples,
    _rejects,
)
from agents.nl_query.tools import IMPLEMENTATIONS, attach
from connectors.loki import tools as loki_tools
from connectors.prometheus import tools as prometheus_tools
from core.contracts.evidence import LogClusterPayload, MetricWindowPayload
from core.contracts.finding import FindingKind
from core.contracts.investigation import Trigger, TriggerKind
from core.contracts.llm import Tier
from core.llm.provider import ProviderError
from core.registry.loader import for_codename

END = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
SPAN = timedelta(minutes=30)

PROMETHEUS_RESULT = {
    "resultType": "vector",
    "result": [{"metric": {"service": "checkout"}, "value": [1756382400, "0.42"]}],
}
LOKI_RESULT = {
    "resultType": "streams",
    "result": [{"stream": {"service": "checkout"}, "values": [["1", "boom"], ["2", "bang"]]}],
}


class _Scripted:
    """A Delphi whose replies are a list, in order.

    A provider-level fake would make each test carry the whole catalogue and
    resolver; this substitutes at the seam Hermes actually depends on.
    """

    def __init__(self, *replies: str, fail: Exception | None = None) -> None:
        self.replies = list(replies)
        self.fail = fail
        self.prompts: list[str] = []
        self.tiers: list[Tier] = []

    async def consult(self, requirements: Any, **kwargs: Any) -> Any:
        if self.fail is not None:
            raise self.fail
        self.prompts.append(str(kwargs.get("prompt", "")))
        self.tiers.append(requirements.tier)
        return _Consultation(self.replies.pop(0) if self.replies else "{}")

    def plan_prompts(self) -> list[str]:
        """Only the planning calls. The summarising call carries the result."""
        return [prompt for prompt in self.prompts if "Result:" not in prompt]


class _Consultation:
    """The two fields Hermes reads off a `Consultation`."""

    def __init__(self, text: str) -> None:
        self.completion = _Completion(text)
        self.record = f"record:{text[:20]}"


class _Completion:
    def __init__(self, text: str) -> None:
        self.text = text


class _Tools:
    """A connector surface that records what it was asked."""

    def __init__(self, result: Any = None, fail: bool = False) -> None:
        self.result = result if result is not None else PROMETHEUS_RESULT
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, /, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        if self.fail:
            raise RuntimeError("prometheus is unreachable")
        return self.result


def _plan(tool: str = "prometheus.query_instant", query: str = "up") -> str:
    return json.dumps({"tool": tool, "query": query, "why": "because"})


def _hermes(
    delphi: _Scripted, tools: _Tools | None = None, *, question: str = "what is the error rate?"
) -> tuple[Hermes, AgentContext, _Tools]:
    surface = tools or _Tools()
    agent = Hermes(delphi=delphi)  # type: ignore[arg-type]
    ctx = AgentContext(
        investigation_id=uuid4(),
        trigger=Trigger(kind=TriggerKind.SIMULATION, received_at=END, source="test"),
        window_start=END - SPAN,
        window_end=END,
        params={"question": question} if question else {},
    )
    ctx.tools = surface
    return agent, ctx, surface


# --- the model proposes; Hermes decides -----------------------------------------


@pytest.mark.asyncio
async def test_a_tool_the_model_invented_is_refused_before_it_is_called() -> None:
    """`tool_binding` would refuse it too - at which point the error reads as a
    missing connector rather than as a model that invented a capability."""
    delphi = _Scripted(_plan(tool="kubernetes.delete_everything"), _plan(tool="shell.exec"))
    agent, ctx, tools = _hermes(delphi)

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert tools.calls == [], "an invented tool reached the connector layer"
    assert "is not one of" in str(raised.value)


@pytest.mark.asyncio
async def test_the_model_does_not_choose_the_time_range() -> None:
    """The window is a fact about the investigation, not a thing to guess at.

    A model asking for thirty days would be answering a different question and
    reading a much larger one out of Prometheus.
    """
    # A start the model supplied, which Hermes must ignore rather than honour.
    delphi = _Scripted(
        json.dumps({"tool": "loki.query_range", "query": '{a="b"}', "start": "-30d"})
    )
    agent, ctx, tools = _hermes(delphi)

    await agent.investigate(ctx)

    _name, kwargs = tools.calls[0]
    assert kwargs["start"] == str(int((END - SPAN).timestamp() * 1_000_000_000))
    assert kwargs["end"] == str(int(END.timestamp() * 1_000_000_000))


@pytest.mark.asyncio
async def test_a_reply_that_is_not_json_is_refused() -> None:
    delphi = _Scripted("I think you should check the dashboard", "still not JSON")
    agent, ctx, tools = _hermes(delphi)

    with pytest.raises(AgentDegraded, match="not JSON"):
        await agent.investigate(ctx)
    assert tools.calls == []


@pytest.mark.asyncio
async def test_a_model_saying_it_cannot_answer_is_believed() -> None:
    """A null tool is a refusal, and forcing a query out of it would run
    something nobody had a reason to run."""
    refusal = json.dumps({"tool": None, "query": None, "why": "no connector has deploy history"})
    delphi = _Scripted(refusal, refusal)
    agent, ctx, tools = _hermes(delphi)

    with pytest.raises(AgentDegraded, match="deploy history"):
        await agent.investigate(ctx)
    assert tools.calls == []


@pytest.mark.asyncio
async def test_a_rejected_plan_is_retold_what_was_wrong() -> None:
    """One attempt discards a plan a sentence would have fixed."""
    delphi = _Scripted("nonsense", _plan())
    agent, ctx, tools = _hermes(delphi)

    findings = await agent.investigate(ctx)

    assert len(delphi.plan_prompts()) == 2, "the plan was not retried exactly once"
    assert "rejected" in delphi.plan_prompts()[1], "the second attempt was not told what was wrong"
    assert len(findings) == 1
    assert len(tools.calls) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded() -> None:
    """Unbounded retries spend the whole budget re-reading the same mistake."""
    delphi = _Scripted(*["nonsense"] * 10)
    agent, ctx, _tools = _hermes(delphi)

    with pytest.raises(AgentDegraded):
        await agent.investigate(ctx)

    assert len(delphi.plan_prompts()) == MAX_PLAN_ATTEMPTS


# --- no data means no answer ------------------------------------------------------


@pytest.mark.asyncio
async def test_an_empty_result_is_reported_without_consulting_a_model() -> None:
    """Handing an empty result to a summariser is how "no error rows" becomes
    "the service is healthy" - a claim about the world from an absence."""
    delphi = _Scripted(_plan())
    agent, ctx, _tools = _hermes(delphi, _Tools(result={"resultType": "vector", "result": []}))

    findings = await agent.investigate(ctx)

    assert len(delphi.prompts) == 1, "a model was asked to interpret an empty result"
    assert len(findings) == 1
    assert "empty-result" in findings[0].tags
    assert "no data" in findings[0].title


@pytest.mark.asyncio
async def test_an_empty_result_does_not_claim_anything_is_well() -> None:
    delphi = _Scripted(_plan())
    agent, ctx, _tools = _hermes(delphi, _Tools(result={"result": []}))

    rationale = (await agent.investigate(ctx))[0].rationale or ""

    assert "not a statement about whether anything is wrong" in rationale


@pytest.mark.asyncio
async def test_a_connector_that_failed_is_not_reported_as_an_empty_answer() -> None:
    """Unanswered and answered-with-nothing are different facts."""
    delphi = _Scripted(_plan())
    agent, ctx, _tools = _hermes(delphi, _Tools(fail=True))

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert raised.value.retryable
    assert "different from the answer being nothing" in str(raised.value)


# --- the answer is checkable ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_raw_result_is_attached_so_the_answer_can_be_checked() -> None:
    delphi = _Scripted(_plan(), "The error rate is 0.42.")
    agent, ctx, _tools = _hermes(delphi)

    finding = (await agent.investigate(ctx))[0]

    assert finding.kind is FindingKind.OBSERVATION
    assert finding.rationale == "The error rate is 0.42."
    payload = finding.evidence[0].payload
    assert isinstance(payload, MetricWindowPayload)
    assert [sample.value for sample in payload.samples] == [0.42]


@pytest.mark.asyncio
async def test_a_log_answer_carries_the_lines_it_was_built_from() -> None:
    delphi = _Scripted(_plan(tool="loki.query_range", query='{a="b"}'), "Two errors.")
    agent, ctx, _tools = _hermes(delphi, _Tools(result=LOKI_RESULT))

    payload = (await agent.investigate(ctx))[0].evidence[0].payload

    assert isinstance(payload, LogClusterPayload)
    assert payload.sample_lines == ["boom", "bang"]
    assert payload.novelty is None, "Hermes compares nothing, so it has no novelty to claim"


@pytest.mark.asyncio
async def test_confidence_is_not_dressed_up_as_a_measurement() -> None:
    """An answer is exactly as good as the query behind it, and Hermes cannot
    score that. A number would be the model's self-assessment in disguise."""
    delphi = _Scripted(_plan(), "0.42")
    agent, ctx, _tools = _hermes(delphi)

    finding = (await agent.investigate(ctx))[0]

    assert "confidence:not-a-measurement" in finding.tags


# --- refusals ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_question_is_a_refusal_rather_than_a_default_one() -> None:
    delphi = _Scripted(_plan())
    agent, ctx, tools = _hermes(delphi, question="")

    with pytest.raises(AgentDegraded, match="no question"):
        await agent.investigate(ctx)
    assert tools.calls == []
    assert delphi.prompts == [], "a model was consulted with no question to answer"


@pytest.mark.asyncio
async def test_an_unreachable_model_degrades_and_runs_nothing() -> None:
    delphi = _Scripted(fail=ProviderError("no key configured", retryable=False))
    agent, ctx, tools = _hermes(delphi)

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert "could not be consulted" in str(raised.value)
    assert tools.calls == []


# --- ADR 0004: an agent declares requirements, never a model ------------------------


@pytest.mark.asyncio
async def test_hermes_never_names_a_model() -> None:
    """The invariant ADR 0004 exists for. Asserted on the source, because a
    model id can be introduced anywhere and a runtime check would only catch
    the paths a test happens to walk."""
    from pathlib import Path

    from tests.mechanism import read_mechanism

    source = read_mechanism(Path("agents/nl_query/agent.py"))
    for shape in ("gpt-", "claude-", "llama", "gemini", "mistral", "qwen"):
        assert shape not in source.lower(), f"Hermes names a model: {shape!r}"


@pytest.mark.asyncio
async def test_planning_asks_for_a_capability_and_a_tier() -> None:
    """Requirements, not a name. Structured output is a capability the resolver
    can check; "use the good model" is not."""
    delphi = _Scripted(_plan(), "answer")
    agent, ctx, _tools = _hermes(delphi)

    await agent.investigate(ctx)

    assert delphi.tiers[0] is Tier.BALANCED, "planning asked for the wrong tier"
    assert delphi.tiers[1] is Tier.CHEAP, "summarising should not need the balanced tier"


@pytest.mark.asyncio
async def test_every_consultation_is_recorded_even_the_rejected_one() -> None:
    """A run that degraded still spent the money. A cost record that only
    survives success cannot answer "what did this cost" for the runs anyone
    actually asks about."""
    delphi = _Scripted("nonsense", _plan(), "answer")
    agent, ctx, _tools = _hermes(delphi)

    await agent.investigate(ctx)

    assert len(ctx.resolutions) == 3, (
        f"{len(ctx.resolutions)} resolutions recorded; expected the rejected plan, "
        "the accepted plan and the answer"
    )


# --- the manifest and the implementation agree --------------------------------------


def test_hermes_implements_exactly_the_tools_its_manifest_declares() -> None:
    declared = set(for_codename("hermes").tools)
    assert declared == set(IMPLEMENTATIONS), (
        f"the manifest declares {sorted(declared)}; tools.py implements {sorted(IMPLEMENTATIONS)}"
    )


def test_attaching_cannot_widen_the_allowlist() -> None:
    tools = BoundTools(declared=frozenset({"loki.query_range"}), max_calls=10)
    attach(tools)

    assert "prometheus.query_instant" not in tools._implementations
    with pytest.raises(ToolNotDeclared):
        tools.register("shell.exec", IMPLEMENTATIONS["loki.query_range"])


# --- the parsers, on shapes a connector could actually return -----------------------


@pytest.mark.parametrize(
    ("result", "empty"),
    [
        (None, True),
        ({}, True),
        ({"result": []}, True),
        ([], True),
        ({"result": [{"value": [1, "1"]}]}, False),
    ],
)
def test_what_counts_as_no_data(result: Any, empty: bool) -> None:
    """`None` is included deliberately: a connector that returned nothing at all
    is also nothing, and treating it as data would put `null` in front of a
    summariser."""
    assert _is_empty(result) is empty


@pytest.mark.parametrize(
    "result",
    ["a string", {"result": [{}]}, {"result": [{"value": []}]}, {"result": [{"value": [1]}]}],
)
def test_a_shape_the_sample_reader_cannot_parse_yields_nothing_rather_than_raising(
    result: Any,
) -> None:
    """The raw result is on the Evidence either way, so a reader can see what
    came back even when this could not read it. Raising here would turn an
    unfamiliar response into a crashed agent."""
    assert _metric_samples(result, END) == []


def test_a_non_numeric_metric_value_is_skipped_not_coerced() -> None:
    """Prometheus sends `NaN` and `+Inf` as strings. Coercing one into a sample
    would put a number in front of an operator that the series never had."""
    result = {"result": [{"value": [1, "not-a-number"]}, {"value": [1, "0.5"]}]}
    assert [sample.value for sample in _metric_samples(result, END)] == [0.5]


@pytest.mark.parametrize("result", ["a string", {"result": [{"values": [["1"]]}]}])
def test_a_log_shape_the_line_reader_cannot_parse_yields_nothing(result: Any) -> None:
    assert _log_lines(result) == []


def test_a_reply_that_is_json_but_not_an_object_is_refused() -> None:
    """`["up"]` parses. It is still not a plan."""
    assert "not an object" in _rejects(json.dumps(["up"]))


@pytest.mark.parametrize("query", ["", "   ", None, 42])
def test_a_plan_with_no_usable_query_is_refused(query: Any) -> None:
    plan = json.dumps({"tool": "prometheus.query_instant", "query": query})
    assert "no query string" in _rejects(plan)


@pytest.mark.asyncio
async def test_a_summariser_that_fails_does_not_discard_the_query_that_worked() -> None:
    """The distinction the message has to keep: the query ran."""

    class _FailsOnAnswer(_Scripted):
        async def consult(self, requirements: Any, **kwargs: Any) -> Any:
            if "Result:" in str(kwargs.get("prompt", "")):
                raise ProviderError("summariser is down", retryable=True)
            return await super().consult(requirements, **kwargs)

    agent, ctx, _tools = _hermes(_FailsOnAnswer(_plan()))

    with pytest.raises(AgentDegraded, match="ran but its result could not be summarised"):
        await agent.investigate(ctx)


# --- the adapters translate keywords into what the connector expects ---------------


@pytest.mark.asyncio
async def test_the_instant_adapter_passes_the_query_and_the_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def capture(arguments: dict[str, Any]) -> Any:
        seen.update(arguments)
        return PROMETHEUS_RESULT

    monkeypatch.setattr(prometheus_tools, "query_instant", capture)
    await IMPLEMENTATIONS["prometheus.query_instant"](query="up", time=1.0)

    assert seen == {"query": "up", "time": 1.0}


@pytest.mark.asyncio
async def test_the_log_adapter_defaults_direction_and_passes_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped limit reads as Loki's own default of 100, which truncates - and
    a truncated answer looks exactly like a quiet service."""
    seen: dict[str, Any] = {}

    async def capture(arguments: dict[str, Any]) -> Any:
        seen.update(arguments)
        return LOKI_RESULT

    monkeypatch.setattr(loki_tools, "query_range", capture)
    await IMPLEMENTATIONS["loki.query_range"](query='{a="b"}', start="1", end="2", limit=200)

    assert seen == {
        "query": '{a="b"}',
        "start": "1",
        "end": "2",
        "limit": 200,
        "direction": "backward",
    }
