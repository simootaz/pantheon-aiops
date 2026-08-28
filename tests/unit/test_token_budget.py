"""`AgentBudget.max_tokens`, enforced at last, and the shape of that enforcement.

Until 2026-08-28 a guard asserted this field stayed UNREAD - nothing consumed
tokens, so there was no meter, and an enforcement path with nothing to test
against is the unfailable-guard class. Delphi landed and `Completion` carries
token counts, so the field is connected and that guard is retired.

The interesting cases are the ones where enforcement could be present and
useless: charging after the fact, estimating optimistically, or letting an agent
catch the refusal and carry on.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents._base.base_agent import AgentContext, AgentStatus, BaseAgent, _estimate_tokens
from agents._base.testing import a_context
from core.contracts.finding import Finding, FindingKind
from core.contracts.llm import ModelRequirements, Tier
from core.guardrails.budget import TokenBudgetExceeded, TokenMeter


class _Completion:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.text = "answered"
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Consultation:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.completion = _Completion(prompt_tokens, completion_tokens)
        self.record = "a record"


class _Gateway:
    """A gateway that reports a fixed token cost and counts its calls."""

    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 10) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls = 0

    async def consult(self, requirements: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return _Consultation(self.prompt_tokens, self.completion_tokens)


class _Consulting(BaseAgent):
    """An agent that consults `times` times and reports what it spent."""

    domain = "anomaly"

    def __init__(self, times: int, *, max_tokens: int = 100, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._times = times
        self._max_tokens = max_tokens

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        for _ in range(self._times):
            await self.consult(
                ctx, ModelRequirements(tier=Tier.CHEAP), prompt="hi", max_tokens=self._max_tokens
            )
        return []


# --- the meter itself -------------------------------------------------------------


def test_a_request_that_could_not_fit_is_refused_before_it_is_made() -> None:
    """A meter that only charges afterwards cannot stop anything: the tokens are
    already spent and the money is already gone."""
    meter = TokenMeter(ceiling=100)

    with pytest.raises(TokenBudgetExceeded, match="needs up to 500"):
        meter.check(requested_by="argus", worst_case=500)

    assert meter.spent == 0, "a refused request was charged"


def test_the_worst_case_is_used_and_not_an_expectation() -> None:
    """Assuming a completion will be shorter than the caller allowed is an
    assumption about output made before any output exists."""
    meter = TokenMeter(ceiling=100)

    meter.check(requested_by="argus", worst_case=100)
    with pytest.raises(TokenBudgetExceeded):
        meter.check(requested_by="argus", worst_case=101)


def test_an_overrun_is_still_recorded() -> None:
    """The tokens were spent. A meter that refused to record an overrun would
    report a total lower than the bill."""
    meter = TokenMeter(ceiling=10)
    meter.charge(requested_by="argus", prompt_tokens=50, completion_tokens=50)

    assert meter.spent == 100
    assert meter.remaining == 0
    with pytest.raises(TokenBudgetExceeded):
        meter.check(requested_by="argus", worst_case=1)


def test_the_meter_records_which_call_spent_what() -> None:
    """ "Which call blew the budget" is the first question asked, and a running
    total cannot answer it."""
    meter = TokenMeter(ceiling=1000)
    meter.charge(requested_by="hermes", prompt_tokens=10, completion_tokens=5)
    meter.charge(requested_by="hermes", prompt_tokens=200, completion_tokens=100)

    assert meter.charges == [("hermes", 15), ("hermes", 300)]
    assert meter.as_dict()["calls"] == 2


def test_a_negative_report_from_a_provider_cannot_refund_the_budget() -> None:
    """A provider reporting -1 tokens would otherwise buy back spend that
    happened, and a budget that can go up is not a budget."""
    meter = TokenMeter(ceiling=100)
    meter.charge(requested_by="argus", prompt_tokens=50, completion_tokens=0)
    meter.charge(requested_by="argus", prompt_tokens=-40, completion_tokens=-40)

    assert meter.spent == 50


def test_remaining_never_goes_negative() -> None:
    """It is read into messages and reports; a negative would read as credit."""
    meter = TokenMeter(ceiling=10)
    meter.charge(requested_by="argus", prompt_tokens=100, completion_tokens=0)

    assert meter.remaining == 0


# --- the estimate ------------------------------------------------------------------


def test_the_estimate_errs_towards_refusing() -> None:
    """Four characters per token is the rule of thumb and it UNDER-counts for
    code, JSON and non-Latin scripts - all of which agents send. Under-counting
    lets through a call that should have been refused, so this uses three."""
    text = "x" * 120

    assert _estimate_tokens(text) >= len(text) // 4


def test_the_estimate_is_never_zero() -> None:
    """A zero estimate makes an unbounded number of tiny calls free."""
    assert _estimate_tokens("") >= 1
    assert _estimate_tokens("a") >= 1


# --- through the runtime -----------------------------------------------------------


def test_an_agent_within_its_budget_completes() -> None:
    """The control. A meter that refused everything would pass every test below."""
    agent = _Consulting(times=2, max_tokens=10, delphi=_Gateway())
    outcome = asyncio.run(agent.run(a_context()))

    assert outcome.status is AgentStatus.COMPLETE


def test_an_agent_that_would_exceed_its_budget_is_stopped_and_says_so() -> None:
    """The manifest says 16384; asking for more than that in one call is refused
    before the provider is reached."""
    gateway = _Gateway()
    agent = _Consulting(times=1, max_tokens=1_000_000, delphi=gateway)

    outcome = asyncio.run(agent.run(a_context()))

    assert outcome.status is AgentStatus.DEGRADED
    assert gateway.calls == 0, "the provider was called despite the budget being blown"
    assert "tokens" in (outcome.degraded_reason or "")


def test_exhaustion_produces_a_degraded_finding_rather_than_an_exception() -> None:
    """The runtime owns DEGRADED, so a spent budget is reported the same way a
    timeout or a tool-budget exhaustion is."""
    agent = _Consulting(times=1, max_tokens=1_000_000, delphi=_Gateway())

    outcome = asyncio.run(agent.run(a_context()))

    assert [f.kind for f in outcome.findings] == [FindingKind.DEGRADED]
    assert outcome.retryable is False, "a budget will be just as spent on a retry"


def test_spend_accumulates_across_calls_within_one_run() -> None:
    """A budget enforced per-call and not per-run is not a run budget."""
    gateway = _Gateway(prompt_tokens=100, completion_tokens=100)
    agent = _Consulting(times=3, max_tokens=10, delphi=gateway)
    ctx = a_context()

    asyncio.run(agent.run(ctx))

    assert ctx.meter is not None
    assert ctx.meter.spent == 600, f"charged {ctx.meter.spent} across three calls"


def test_a_run_stops_once_its_budget_is_gone() -> None:
    """Not "warns and continues". The next check is what ends the run."""
    # 16384 ceiling, 6000 tokens reported per call: the third check cannot fit.
    gateway = _Gateway(prompt_tokens=3000, completion_tokens=3000)
    agent = _Consulting(times=10, max_tokens=5000, delphi=gateway)

    outcome = asyncio.run(agent.run(a_context()))

    assert outcome.status is AgentStatus.DEGRADED
    assert gateway.calls < 10, "the agent kept consulting after its budget was gone"


def test_consulting_outside_a_run_is_refused_rather_than_unmetered() -> None:
    """`investigate` called directly - which is how Argus's toolset bug hid -
    must not silently spend without a ceiling."""
    agent = _Consulting(times=1, delphi=_Gateway())
    ctx = AgentContext(
        investigation_id=a_context().investigation_id,
        trigger=a_context().trigger,
        window_start=a_context().window_start,
        window_end=a_context().window_end,
    )

    with pytest.raises(RuntimeError, match="no token meter"):
        asyncio.run(agent.investigate(ctx))


def test_the_meter_is_reported_in_a_readable_shape() -> None:
    """For a DEGRADED Finding's tags, and for anything reporting spend."""
    meter = TokenMeter(ceiling=100)
    meter.charge(requested_by="argus", prompt_tokens=30, completion_tokens=0)

    assert meter.as_dict() == {"ceiling": 100, "spent": 30, "remaining": 70, "calls": 1}
