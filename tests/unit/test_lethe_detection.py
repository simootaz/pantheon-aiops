"""What Lethe emits, refuses and never claims - the properties needing no stack.

The negative cases are the point. A detector that reports something for every
window would pass every positive test here and be worse than no detector, so a
clean pair of windows must produce **no Findings at all** - not an empty one,
not a quiet one.

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
from agents.log_clustering.agent import MIN_LINES_TO_TEMPLATE, SELECTOR, Lethe
from agents.log_clustering.tools import IMPLEMENTATIONS, attach
from connectors.loki import tools as loki_tools
from core.contracts.evidence import EvidenceKind, LogClusterPayload
from core.contracts.finding import FindingKind
from core.contracts.investigation import Trigger, TriggerKind
from core.registry.loader import for_codename


def _payload(finding: Any) -> LogClusterPayload:
    """The Evidence payload, narrowed.

    `Evidence.payload` is a union across every evidence kind, so a test reading
    `.template` off it is asserting a shape mypy cannot see. Narrowing here makes
    the wrong-kind case a failure with a message instead of an attribute error.
    """
    payload = finding.evidence[0].payload
    assert isinstance(payload, LogClusterPayload), f"expected a log cluster, got {type(payload)}"
    return payload


END = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
SPAN = timedelta(minutes=30)


#: How many distinct timestamps a window carries. FEW, on purpose: a compressed
#: run stamps thousands of lines with a handful of seconds, and that is the case
#: where cardinality cannot tell a clock from a category.
#:
#: Sized so the POOLED corpus stays under MAX_STABLE_VALUES, not just each
#: window: `compare()` learns one classification over both, so two windows of six
#: disjoint stamps pool to twelve and the cap masks the clock on its own. At
#: twelve, and then at six, deleting the ordering rule produced no failure at all
#: - the fixture was testing the cap and claiming to test the clock.
DISTINCT_STAMPS = 4


def _requests(count: int, *, path: str = "/api/cart", start: int = 0) -> list[str]:
    """Ordinary traffic, stamped the way a compressed run stamps it."""
    return [
        json.dumps(
            {
                "ts": _stamp(start + (index * DISTINCT_STAMPS) // max(count, 1)),
                "level": "info",
                "msg": "request completed",
                "path": path,
                "status": 200,
                "duration_ms": 40 + index % 37,
            }
        )
        for index in range(count)
    ]


def _stamp(tick: int) -> str:
    return f"2026-08-27T11:{tick // 60 % 60:02d}:{tick % 60:02d}Z"


def _disk(count: int) -> list[str]:
    return [
        json.dumps(
            {
                "ts": _stamp((index * DISTINCT_STAMPS) // max(count, 1)),
                "level": "warn",
                "msg": "disk usage high",
                "mount": "/var/lib/containerd",
                "used_percent": 86.0 + index % 11,
            }
        )
        for index in range(count)
    ]


def _trace(count: int) -> list[str]:
    return [
        json.dumps(
            {
                "level": "error",
                "msg": "unhandled exception",
                "exception": "java.lang.OutOfMemoryError: Java heap space",
                "stack": (
                    f"at com.acme.checkout.Handler.process(Handler.java:{100 + index})\n"
                    f"\tat com.acme.checkout.Router.dispatch(Router.java:{200 + index})"
                ),
            }
        )
        for index in range(count)
    ]


class _Loki:
    """A tool surface answering each window with the lines it was given.

    Keyed by which window is asked for rather than by call order, because a test
    that depends on the agent reading the incident first would pass for a reason
    unrelated to what it claims.
    """

    def __init__(self, incident: list[str], reference: list[str], *, fail: bool = False) -> None:
        self.incident = incident
        self.reference = reference
        self.fail = fail
        self.calls: list[tuple[int, int]] = []

    async def call(self, name: str, /, **kwargs: Any) -> Any:
        assert name == "loki.query_range", name
        if self.fail:
            raise RuntimeError("loki is unreachable")

        start, end = int(kwargs["start"]), int(kwargs["end"])
        self.calls.append((start, end))
        incident_from = int(END.timestamp() - SPAN.total_seconds()) * 1_000_000_000
        lines = self.incident if start >= incident_from else self.reference

        # One stream, stamped in order. The agent sorts by these, so handing back
        # a single ordered stream is the least helpful shape for it - a test that
        # pre-sorted would hide a missing sort in the agent.
        base = start
        return {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"scope": "lethe-test"},
                    "values": [[str(base + index), line] for index, line in enumerate(lines)],
                }
            ],
        }


def _context() -> AgentContext:
    return AgentContext(
        investigation_id=uuid4(),
        trigger=Trigger(kind=TriggerKind.SIMULATION, received_at=END, source="test"),
        window_start=END - SPAN,
        window_end=END,
    )


def _lethe(tools: _Loki) -> tuple[Lethe, AgentContext]:
    agent = Lethe()
    ctx = _context()
    ctx.tools = tools
    return agent, ctx


def _enough() -> int:
    return MIN_LINES_TO_TEMPLATE + 200


# --- the negative direction, which is the point ---------------------------------


@pytest.mark.asyncio
async def test_two_clean_windows_produce_no_findings_at_all() -> None:
    """Not an empty Finding, not a quiet one. Nothing.

    A detector that reports on every window passes every positive test below and
    is worse than no detector.
    """
    tools = _Loki(_requests(_enough()), _requests(_enough(), start=900))
    agent, ctx = _lethe(tools)

    assert await agent.investigate(ctx) == []


@pytest.mark.asyncio
async def test_a_pattern_the_reference_already_had_is_not_reported() -> None:
    """The measured blind spot, asserted so it cannot be forgotten.

    `bad_deploy_5xx` multiplies a pattern the baseline already contains rather
    than introducing one, and Lethe cannot see that. Stated in the module
    docstring and pinned here, because a limitation only in prose gets quietly
    fixed-by-accident and then quietly re-broken.
    """
    reference = _requests(_enough()) + _disk(20)
    incident = _requests(_enough()) + _disk(400)
    agent, ctx = _lethe(_Loki(incident, reference))

    findings = await agent.investigate(ctx)

    assert findings == [], (
        "a 20x rate increase in a known pattern was reported as a finding. Lethe "
        "has no rate test - surged() was deleted because it could not tell a "
        "fault from the time of day - so this must stay silent until a peer-"
        "relative one exists."
    )


# --- the positive direction ------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pattern_absent_from_the_reference_is_reported() -> None:
    tools = _Loki(_requests(_enough()) + _disk(60), _requests(_enough()))
    agent, ctx = _lethe(tools)

    findings = await agent.investigate(ctx)

    assert len(findings) == 1, [f.title for f in findings]
    finding = findings[0]
    assert finding.kind is FindingKind.ANOMALY
    assert "disk usage high" in finding.title
    assert finding.evidence[0].kind is EvidenceKind.LOG_CLUSTER
    assert _payload(finding).occurrences == 60
    assert "novel-template" in finding.tags


@pytest.mark.asyncio
async def test_the_finding_reports_both_window_sizes() -> None:
    """A novelty claim is only readable beside what it was measured against."""
    agent, ctx = _lethe(_Loki(_requests(_enough()) + _disk(60), _requests(_enough())))

    tags = (await agent.investigate(ctx))[0].tags

    assert any(tag.startswith("reference-lines:") for tag in tags)
    assert any(tag.startswith("incident-lines:") for tag in tags)


@pytest.mark.asyncio
async def test_confidence_is_the_tail_probability_and_says_so() -> None:
    """A bare number invites being read as a vibe."""
    agent, ctx = _lethe(_Loki(_requests(_enough()) + _disk(60), _requests(_enough())))

    finding = (await agent.investigate(ctx))[0]

    assert 0.0 <= finding.confidence <= 1.0
    assert finding.confidence > 0.95, "a pattern absent 60 times over should be near-certain"
    assert "confidence:absence-surprise" in finding.tags


@pytest.mark.asyncio
async def test_an_exception_is_reported_once_however_often_it_was_thrown() -> None:
    """Forty throws of one bug is one fault, not forty findings."""
    agent, ctx = _lethe(_Loki(_requests(_enough()) + _trace(40), _requests(_enough())))

    traces = [f for f in await agent.investigate(ctx) if "stack-trace" in f.tags]

    assert len(traces) == 1
    assert traces[0].kind is FindingKind.OBSERVATION
    assert "OutOfMemoryError" in traces[0].title
    assert _payload(traces[0]).occurrences == 40


@pytest.mark.asyncio
async def test_an_extracted_trace_claims_no_novelty() -> None:
    """It is not compared against a reference, so a novelty number would be an
    assertion nothing measured."""
    agent, ctx = _lethe(_Loki(_requests(_enough()) + _trace(40), _requests(_enough())))

    trace = next(f for f in await agent.investigate(ctx) if "stack-trace" in f.tags)

    assert _payload(trace).novelty is None
    assert trace.confidence == 1.0


# --- refusals are reported, not silent -------------------------------------------


@pytest.mark.asyncio
async def test_an_unreachable_loki_degrades_rather_than_reporting_nothing() -> None:
    """Nothing was scanned, which is different from finding nothing."""
    agent, ctx = _lethe(_Loki([], [], fail=True))

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert raised.value.retryable, "an unreachable connector is worth retrying"
    assert "loki could not be read" in str(raised.value)


@pytest.mark.asyncio
async def test_a_window_too_small_to_template_refuses_and_says_why() -> None:
    agent, ctx = _lethe(_Loki(_requests(50), _requests(_enough())))

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert not raised.value.retryable, "a short window will be short on retry too"
    assert "below the" in str(raised.value)


@pytest.mark.asyncio
async def test_a_thin_reference_refuses_rather_than_calling_everything_novel() -> None:
    """Everything would look new against an empty reference - which is a
    statement about the reference, not about the incident."""
    agent, ctx = _lethe(_Loki(_requests(_enough()), _requests(10)))

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert "reference window" in str(raised.value)


@pytest.mark.asyncio
async def test_a_refusal_still_carries_what_was_found() -> None:
    """A partial scan survives. Traces are extracted before templating, so a
    window too thin to template can still report the exception in it."""
    agent, ctx = _lethe(_Loki(_trace(40) + _requests(20), _requests(_enough())))

    with pytest.raises(AgentDegraded) as raised:
        await agent.investigate(ctx)

    assert raised.value.partial, "the traces found before the refusal were dropped"
    assert all("stack-trace" in f.tags for f in raised.value.partial)


@pytest.mark.asyncio
async def test_a_zero_length_window_is_a_caller_error_and_says_so() -> None:
    agent = Lethe()
    ctx = _context()
    ctx.window_start = ctx.window_end
    ctx.tools = _Loki([], [])

    with pytest.raises(AgentDegraded, match="nothing to read"):
        await agent.investigate(ctx)


# --- it reads the window it says it reads ----------------------------------------


@pytest.mark.asyncio
async def test_the_reference_window_is_the_one_immediately_before() -> None:
    """Equal length, ending where the incident window starts. Asserted because
    an off-by-one here compares the incident against itself and reports nothing
    forever, which is indistinguishable from a clean system."""
    tools = _Loki(_requests(_enough()), _requests(_enough(), start=900))
    agent, ctx = _lethe(tools)
    await agent.investigate(ctx)

    incident, reference = sorted(tools.calls, reverse=True)
    span = SPAN.total_seconds() * 1_000_000_000

    assert incident[1] - incident[0] == pytest.approx(span, rel=1e-6)
    assert reference[1] - reference[0] == pytest.approx(span, rel=1e-6)
    assert reference[1] == pytest.approx(incident[0], rel=1e-6), (
        "the reference window does not end where the incident window begins"
    )


@pytest.mark.asyncio
async def test_lines_are_sorted_into_emission_order_before_templating() -> None:
    """The shape real Loki returns, which is what defeats an unsorted corpus.

    Not "reversed" - reversing proves nothing, because the ordering rule accepts
    a field that moves consistently in EITHER direction, and a reversed clock is
    still a clock. The first version of this test did exactly that and passed
    against an agent with the sort removed.

    Real Loki returns one stream per label set, each internally in `direction`
    order. Concatenated, a clock runs one way inside a stream and jumps back at
    every boundary - and with few stamps per stream those boundary jumps are a
    large fraction of all the changes there are.
    """

    class _ManyStreams(_Loki):
        """Thirty streams, each in backward order, as the connector returns them."""

        async def call(self, name: str, /, **kwargs: Any) -> Any:
            body = await super().call(name, **kwargs)
            flat = body["result"][0]["values"]
            streams = 30
            body["result"] = [
                {
                    "stream": {"scope": "lethe-test", "pod": f"pod-{group}"},
                    "values": list(reversed(flat[group::streams])),
                }
                for group in range(streams)
            ]
            return body

    tools = _ManyStreams(_requests(_enough()) + _disk(60), _requests(_enough()))
    agent, ctx = _lethe(tools)

    findings = await agent.investigate(ctx)

    assert len(findings) == 1, (
        f"{len(findings)} findings from concatenated streams; the agent is not "
        "sorting by Loki's stamps, so the clock landed inside every template"
    )
    assert "ts=<*>" in _payload(findings[0]).template, (
        "the timestamp survived into the template, so the clock was not detected"
    )


@pytest.mark.asyncio
async def test_a_clock_with_few_distinct_values_is_still_masked() -> None:
    """The case cardinality alone cannot handle, and the reason `_ordered` exists.

    A compressed run stamps thousands of lines with a handful of seconds, so the
    clock is low-cardinality and every cap-based rule calls it a category. Two
    clean windows then share no templates at all and everything looks novel.
    """
    incident = _requests(_enough())
    reference = _requests(_enough(), start=900)

    stamps = {json.loads(line)["ts"] for line in incident}
    assert len(stamps) <= DISTINCT_STAMPS, (
        f"the fixture carries {len(stamps)} distinct stamps; above the cardinality "
        "cap the clock is masked for the wrong reason and this proves nothing"
    )
    assert stamps.isdisjoint({json.loads(line)["ts"] for line in reference}), (
        "the two windows share stamps, so a template keyed on ts would still match"
    )

    agent, ctx = _lethe(_Loki(incident, reference))
    assert await agent.investigate(ctx) == []


# --- the manifest and the implementation agree -----------------------------------


def test_lethe_implements_exactly_the_tools_its_manifest_declares() -> None:
    """A declaration nothing implements makes ToolNotBound the normal case."""
    declared = set(for_codename("lethe").tools)
    assert declared == set(IMPLEMENTATIONS), (
        f"the manifest declares {sorted(declared)}; tools.py implements {sorted(IMPLEMENTATIONS)}"
    )


def test_attaching_cannot_widen_the_allowlist() -> None:
    """`attach` fills the allowlist; it must not be able to extend it."""
    tools = BoundTools(declared=frozenset({"loki.labels"}), max_calls=10)
    attach(tools)

    assert "loki.query_range" not in tools._implementations
    with pytest.raises(ToolNotDeclared):
        tools.register("loki.delete_everything", IMPLEMENTATIONS["loki.labels"])


def test_the_selector_is_the_same_for_both_windows() -> None:
    """A reference read with a different selector is not a reference."""
    assert SELECTOR.startswith("{") and SELECTOR.endswith("}")


# --- the adapters translate keywords into what the connector expects -------------


@pytest.mark.asyncio
async def test_the_range_adapter_passes_every_argument_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The translation layer is where a typo silently sends None.

    A dropped `limit` reads as Loki's own default of 100, which truncates a busy
    window - and a truncated log window looks exactly like a quiet service.
    """
    seen: dict[str, Any] = {}

    async def capture(arguments: dict[str, Any]) -> Any:
        seen.update(arguments)
        return {"result": []}

    monkeypatch.setattr(loki_tools, "query_range", capture)
    await IMPLEMENTATIONS["loki.query_range"](
        query='{a="b"}', start="1", end="2", limit=4000, direction="forward"
    )

    assert seen == {
        "query": '{a="b"}',
        "start": "1",
        "end": "2",
        "limit": 4000,
        "direction": "forward",
    }


@pytest.mark.asyncio
async def test_the_labels_adapter_passes_every_argument_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Declared, implemented, and not called by `investigate` today.

    Tested anyway: an adapter nobody exercises is one that works until the first
    caller, and the manifest says this tool is available.
    """
    seen: dict[str, Any] = {}

    async def capture(arguments: dict[str, Any]) -> Any:
        seen.update(arguments)
        return []

    monkeypatch.setattr(loki_tools, "labels", capture)
    await IMPLEMENTATIONS["loki.labels"](name="service", start="1", end="2")

    assert seen == {"name": "service", "start": "1", "end": "2"}


@pytest.mark.asyncio
async def test_the_range_adapter_defaults_direction_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`direction` has a default; `limit` deliberately does not.

    A silent limit would be a truncation nobody chose. Passing None lets the
    connector apply its own documented default instead.
    """
    seen: dict[str, Any] = {}

    async def capture(arguments: dict[str, Any]) -> Any:
        seen.update(arguments)
        return {"result": []}

    monkeypatch.setattr(loki_tools, "query_range", capture)
    await IMPLEMENTATIONS["loki.query_range"](query='{a="b"}', start="1", end="2")

    assert seen["direction"] == "backward"
    assert seen["limit"] is None
