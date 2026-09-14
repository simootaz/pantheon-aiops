"""A run that was asked something does not get diagnosed.

WHAT WAS WRONG
----------------
Every run's verdict went through `hypotheses.rank`, which turns Findings into
candidate causes. For an alert that is the job. For a question answered by
Hermes it produced an UNKNOWN root cause - "1 finding(s) on service/checkout
that nothing here can attribute to a cause" - under an answer that was never
claimed to be about an incident, and a summary saying Hermes "looked and found
nothing: no metric crossed its calibrated threshold" beside the Finding that
was the whole point. A pull-request review got the same treatment.

The classifier already knew. Its reasons say "answered rather than
investigated" and "reviewed rather than investigated" in words; it just never
told the aggregator. `Classification.explains` is that, as a field.

These run `investigate` end to end rather than calling `aggregate` with the
flag, because the defect was the flag not being passed - a unit test of
`aggregate(explains=False)` would pass with the router still passing nothing.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext, BaseAgent
from core.bus import InMemoryEventBus
from core.contracts.evidence import Evidence, EvidenceSource, LogClusterPayload, ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import Trigger, TriggerKind
from core.orchestrator import dispatcher
from core.orchestrator.classifier import classify
from core.orchestrator.router import investigate
from core.store.investigations import InMemoryInvestigationStore

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _observation(agent: str, title: str) -> Finding:
    subject = ResourceRef(kind="service", name="checkout")
    return Finding(
        id=uuid4(),
        agent=agent,
        kind=FindingKind.OBSERVATION,
        title=title,
        severity=Severity.INFO,
        confidence=1.0,
        detected_at=NOW,
        window_start=NOW - timedelta(minutes=5),
        window_end=NOW,
        subject=subject,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query="q"),
                observed_at=NOW,
                summary="s",
                subject=subject,
                payload=LogClusterPayload(template="answer", occurrences=1),
            )
        ],
    )


class _Answers(BaseAgent):
    """Hermes-shaped: one OBSERVATION that is the answer."""

    domain = "nl_query"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return [_observation(self.codename, "the error rate on checkout is 0.4% over 5m")]


class _Reviews(BaseAgent):
    """Aegis-shaped: a RISK about a change, not an incident."""

    domain = "manifest_review"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        risk = _observation(self.codename, "the change removes checkout's liveness probe")
        return [risk.model_copy(update={"kind": FindingKind.RISK})]


@pytest.fixture
def stubs() -> Any:
    original = dict(dispatcher.AGENTS)
    dispatcher.AGENTS.clear()
    dispatcher.register("hermes", _Answers)
    dispatcher.register("aegis", _Reviews)
    yield
    dispatcher.AGENTS.clear()
    dispatcher.AGENTS.update(original)


def _question() -> Trigger:
    return Trigger(
        kind=TriggerKind.HUMAN_QUESTION,
        received_at=NOW,
        source="dashboard",
        title="what is the error rate?",
        payload={"question": "what is the error rate on checkout?"},
    )


def _pull_request() -> Trigger:
    return Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=NOW,
        source="github",
        title="pull request #12 opened on acme/checkout",
        payload={
            "action": "opened",
            "pull_request": {"number": 12},
            "repository": {"full_name": "acme/checkout"},
        },
    )


def _alert() -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=NOW,
        source="alertmanager",
        title="t",
        payload={"status": "firing", "alerts": [{"labels": {"alertname": "X"}}]},
    )


# --- the classifier says which is which ---------------------------------------------


def test_an_alert_owes_an_explanation_and_a_question_does_not() -> None:
    assert classify(_alert()).explains is True
    assert classify(_question()).explains is False
    assert classify(_pull_request()).explains is False


# --- and the verdict honours it -----------------------------------------------------


@pytest.mark.asyncio
async def test_an_answered_question_is_not_diagnosed(stubs: Any) -> None:
    """No UNKNOWN root cause under an answer.

    The UNKNOWN category exists so "we do not know why" is statable. Attaching
    it to a run that was never asked why says an incident happened and went
    unexplained, and neither half is true.
    """
    verdict = (
        await investigate(_question(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus())
    ).verdict

    assert verdict is not None
    assert verdict.hypotheses == [], [h.statement for h in verdict.hypotheses]
    assert verdict.confidence == 0.0


@pytest.mark.asyncio
async def test_the_answer_is_the_summary(stubs: Any) -> None:
    """Not "hermes looked and found nothing: no metric crossed its calibrated
    threshold". That sentence was written for Argus and was reported for every
    agent whose Finding is not an ANOMALY - which is to say, for the answer."""
    verdict = (
        await investigate(_question(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus())
    ).verdict

    assert verdict is not None
    assert "0.4%" in verdict.summary, verdict.summary
    assert "found nothing" not in verdict.summary
    assert "calibrated threshold" not in verdict.summary


@pytest.mark.asyncio
async def test_a_review_is_not_diagnosed_either(stubs: Any) -> None:
    """A RISK about a change is what Aegis was asked for. Nothing has happened
    yet, so there is no cause to rank it into."""
    verdict = (
        await investigate(
            _pull_request(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus()
        )
    ).verdict

    assert verdict is not None
    assert verdict.hypotheses == []
    assert "liveness probe" in verdict.summary


@pytest.mark.asyncio
async def test_an_alert_still_gets_ranked(stubs: Any) -> None:
    """The control. A change that switched ranking off for everything would pass
    the three tests above and turn every incident into an answer."""
    from core.orchestrator import aggregator
    from core.orchestrator.classifier import Classification

    # Bypass the alert plan's three agents: the question is whether an
    # explaining classification still ranks, not what those agents return.
    finding = _observation("argus", "memory crossed").model_copy(
        update={"kind": FindingKind.ANOMALY}
    )
    explained = aggregator.aggregate(uuid4(), [finding], [], explains=True)
    answered = aggregator.aggregate(uuid4(), [finding], [], explains=False)

    assert explained.hypotheses, "an explaining run produced no hypothesis at all"
    assert answered.hypotheses == []
    assert (
        Classification(
            domains=("anomaly",), severity=Severity.MEDIUM, certain=True, reason="r"
        ).explains
        is True
    ), (
        "the default must be to explain: a new classifier branch that forgets the "
        "field should diagnose, not go quiet"
    )
