"""Themis: what delivery data supports, and what it must refuse to say.

The tests that matter are the refusals. Reporting review latency as DORA lead
time is the most common misuse of these numbers, and it is invisible in the
output - a number appears, it looks plausible, and it measures a shorter thing
than the label claims.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agents._base.base_agent import AgentStatus
from agents._base.testing import a_context
from agents.dora.agent import DEFAULT_WINDOW, Themis
from agents.dora.delivery import MIN_MERGED_FOR_A_PERCENTILE, measure, merged_from
from agents.dora.tools import IMPLEMENTATIONS

REPO = "acme/checkout"
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _pr(number: int, *, opened_days_ago: float, review_hours: float) -> dict[str, Any]:
    opened = NOW - timedelta(days=opened_days_ago)
    return {
        "number": number,
        "created_at": opened.isoformat().replace("+00:00", "Z"),
        "merged_at": (opened + timedelta(hours=review_hours)).isoformat().replace("+00:00", "Z"),
    }


# --- what counts as merged --------------------------------------------------------------


def test_a_pull_request_closed_without_merging_is_not_counted() -> None:
    """It would inflate both numbers: the frequency by work that never shipped,
    and the latency by however long an abandoned branch sat open."""
    closed = {"number": 1, "created_at": NOW.isoformat(), "merged_at": None}

    assert merged_from([closed]) == []


def test_a_negative_review_time_is_dropped() -> None:
    """Clock skew, or a payload nobody should trust. It would drag a median
    below zero and read as instant approval."""
    backwards = {
        "number": 1,
        "created_at": NOW.isoformat(),
        "merged_at": (NOW - timedelta(hours=3)).isoformat(),
    }

    assert merged_from([backwards]) == []


def test_an_unparseable_timestamp_is_dropped_rather_than_fatal() -> None:
    """These come over a wire. One odd entry must not lose the whole
    measurement."""
    assert merged_from([{"number": 1, "created_at": "yesterday", "merged_at": "today"}]) == []


def test_github_z_suffixed_timestamps_parse() -> None:
    """GitHub sends `2026-08-31T12:00:00Z`, which `fromisoformat` refused
    before 3.11 and still refuses in some readings - so the suffix is
    normalised rather than assumed."""
    (one,) = merged_from([_pr(1, opened_days_ago=1, review_hours=5)])

    assert one.review_hours == pytest.approx(5.0)


# --- the window is given, not derived -------------------------------------------------------


def test_the_frequency_uses_the_window_it_was_given() -> None:
    """Deriving the window from the first and last merge would make a quiet
    fortnight look like a busy day: two merges an hour apart would report a
    frequency of 336 a week."""
    merged = merged_from(
        [_pr(1, opened_days_ago=14, review_hours=1), _pr(2, opened_days_ago=14, review_hours=2)]
    )

    delivery = measure(merged, window=timedelta(days=14))

    assert delivery.merge_frequency_per_week == pytest.approx(1.0)


def test_a_zero_length_window_reports_zero_rather_than_dividing_by_it() -> None:
    assert measure([], window=timedelta(0)).merge_frequency_per_week == 0.0


# --- a median needs a sample --------------------------------------------------------------


def test_too_few_merges_produce_no_percentile() -> None:
    """A median of three reviews is a fact about three reviews, not about how
    the team works."""
    merged = merged_from(
        [_pr(n, opened_days_ago=3, review_hours=n) for n in range(1, MIN_MERGED_FOR_A_PERCENTILE)]
    )

    delivery = measure(merged, window=DEFAULT_WINDOW)

    assert delivery.median_review_hours is None
    assert not delivery.has_percentiles
    assert delivery.merged == MIN_MERGED_FOR_A_PERCENTILE - 1


def test_enough_merges_produce_one() -> None:
    """The control. A measure that never computed a percentile would pass the
    test above and be useless."""
    merged = merged_from(
        [
            _pr(n, opened_days_ago=3, review_hours=float(n))
            for n in range(1, MIN_MERGED_FOR_A_PERCENTILE + 1)
        ]
    )

    delivery = measure(merged, window=DEFAULT_WINDOW)

    assert delivery.has_percentiles
    assert delivery.median_review_hours == pytest.approx(3.0)
    assert delivery.slowest_review_hours == pytest.approx(5.0)


def test_one_review_left_open_over_a_holiday_does_not_move_the_median() -> None:
    """Which is why it is a median. A mean would move by days, and the question
    is what a typical review takes."""
    ordinary = [_pr(n, opened_days_ago=3, review_hours=2.0) for n in range(1, 6)]
    outlier = [_pr(99, opened_days_ago=3, review_hours=400.0)]

    with_outlier = measure(merged_from(ordinary + outlier), window=DEFAULT_WINDOW)

    assert with_outlier.median_review_hours == pytest.approx(2.0)
    assert with_outlier.slowest_review_hours == pytest.approx(400.0), "the outlier is still shown"


# --- the agent, and the words it uses ---------------------------------------------------------


class _Forge:
    def __init__(self, payloads: list[dict[str, Any]] | None = None) -> None:
        self.payloads = payloads if payloads is not None else []
        self.calls: list[dict[str, Any]] = []

    async def pull_requests(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.payloads


async def _measure(forge: _Forge, params: dict[str, Any] | None = None) -> Any:
    from agents._base.tool_binding import BoundTools

    agent = Themis()

    def _bind(tools: BoundTools) -> None:
        tools.register("github.pull_requests", forge.pull_requests)

    agent.bind_tools = _bind  # type: ignore[method-assign]
    ctx = a_context()
    ctx.window_end = NOW
    ctx.params = params if params is not None else {"repository": REPO}
    return await agent.run(ctx)


@pytest.mark.asyncio
async def test_the_summary_says_review_latency_is_not_lead_time() -> None:
    """The single most important sentence this agent emits. DORA lead time runs
    from first commit to production; this is open-to-merge, and reporting one as
    the other makes a team look fast by measuring a shorter thing."""
    forge = _Forge([_pr(n, opened_days_ago=3, review_hours=2.0) for n in range(1, 7)])

    outcome = await _measure(forge)

    (finding,) = outcome.findings
    summary = finding.evidence[0].summary
    assert "NOT DORA lead time" in summary
    assert "first commit to production" in summary


@pytest.mark.asyncio
async def test_merge_frequency_is_labelled_a_proxy() -> None:
    """It is deployment frequency only if every merge deploys, which is a claim
    about a pipeline rather than about this data."""
    forge = _Forge([_pr(n, opened_days_ago=3, review_hours=2.0) for n in range(1, 7)])

    outcome = await _measure(forge)

    assert "PROXY" in outcome.findings[0].evidence[0].summary


@pytest.mark.asyncio
async def test_no_dora_performance_band_is_emitted() -> None:
    """elite/high/medium/low are defined against lead time to production.
    Assigning one from review latency would be the same misuse wearing a
    label."""
    forge = _Forge([_pr(n, opened_days_ago=3, review_hours=2.0) for n in range(1, 7)])

    outcome = await _measure(forge)
    (finding,) = outcome.findings
    text = f"{finding.title} {finding.evidence[0].summary}".lower()

    for band in ("elite", "high performer", "medium performer", "low performer"):
        assert band not in text, f"a DORA band ({band}) was assigned from review latency"


@pytest.mark.asyncio
async def test_a_quiet_window_says_so_rather_than_reporting_a_median() -> None:
    forge = _Forge([_pr(1, opened_days_ago=3, review_hours=2.0)])

    outcome = await _measure(forge)

    assert "too few to time a review" in outcome.findings[0].title


@pytest.mark.asyncio
async def test_merges_outside_the_window_are_excluded() -> None:
    """Reading `state=closed` returns the whole history newest-first, so the
    window has to be applied here - otherwise a four-week measurement reports
    four years."""
    forge = _Forge(
        [_pr(n, opened_days_ago=3, review_hours=2.0) for n in range(1, 7)]
        + [_pr(99, opened_days_ago=400, review_hours=2.0)]
    )

    outcome = await _measure(forge)

    assert "6 merges" in outcome.findings[0].evidence[0].summary


@pytest.mark.asyncio
async def test_the_window_can_be_asked_for() -> None:
    """Taken from params rather than from `ctx.window_start`, because the
    investigation window is minutes - the span an alert is about - and a
    delivery measurement over ten minutes measures nothing."""
    forge = _Forge([_pr(n, opened_days_ago=1, review_hours=2.0) for n in range(1, 7)])

    outcome = await _measure(forge, {"repository": REPO, "window_days": 7})

    assert "over 7 days" in outcome.findings[0].evidence[0].summary


@pytest.mark.asyncio
async def test_no_repository_degrades() -> None:
    outcome = await _measure(_Forge(), params={})

    assert outcome.status is AgentStatus.DEGRADED
    assert outcome.degraded_reason is not None
    assert "not an empty result" in outcome.degraded_reason


@pytest.mark.asyncio
async def test_a_repository_with_no_merges_still_answers() -> None:
    """Unlike a detector, this agent is asked a question and always has an
    answer - even when the answer is "nothing merged"."""
    outcome = await _measure(_Forge([]))

    assert outcome.status is AgentStatus.COMPLETE
    assert len(outcome.findings) == 1


@pytest.mark.asyncio
async def test_closed_pull_requests_are_what_is_asked_for() -> None:
    """`state=open` would return work in progress, and an open pull request has
    no review latency because the review has not finished."""
    forge = _Forge([])

    await _measure(forge)

    assert forge.calls[0]["state"] == "closed"


# --- the toolset --------------------------------------------------------------------------------


def test_every_declared_tool_has_an_implementation_and_no_others() -> None:
    assert set(Themis().manifest.tools) == set(IMPLEMENTATIONS)
    assert set(IMPLEMENTATIONS) == {"github.pull_requests"}


def test_the_capabilities_claim_only_what_is_produced() -> None:
    """`compute_dora` claimed four metrics and two are not computable;
    `assess_delivery_trend` compared two small samples. Both are gone rather
    than unimplemented - a declared capability nothing performs reads as one
    that works."""
    capabilities = {capability.name for capability in Themis().manifest.capabilities}

    assert capabilities == {"measure_delivery"}
    assert not [tool for tool in Themis().manifest.tools if tool.startswith("gitlab.")]


@pytest.mark.asyncio
async def test_the_declared_adapter_reaches_the_connector(monkeypatch: Any) -> None:
    """Through `attach` and the real adapter, with only the transport faked."""
    import httpx

    from agents._base.tool_binding import BoundTools
    from agents.dora.tools import attach

    seen: list[str] = []
    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> Any:
        def _answer(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=[])

        kwargs["transport"] = httpx.MockTransport(_answer)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    tools = BoundTools(declared=frozenset(IMPLEMENTATIONS), max_calls=5)
    attach(tools)

    await tools.call("github.pull_requests", repository=REPO, state="closed")

    assert seen[0].split("?")[0].endswith(f"/repos/{REPO}/pulls")
    assert "state=closed" in seen[0]
