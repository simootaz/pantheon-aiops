"""Zeus: what it plans, what it dispatches, and what its Verdict refuses to claim.

The live gate is `tests/integration/test_flow_one.py`. These are the properties
that need no stack.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from core.bus import InMemoryEventBus
from core.contracts.events import InvestigationCompletedEvent
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import InvestigationState, Trigger, TriggerKind
from core.contracts.plan import StepStatus
from core.orchestrator import aggregator, dispatcher, planner
from core.orchestrator.classifier import Classification, classify, scenario_of
from core.orchestrator.router import investigate
from core.registry import loader
from core.store.investigations import InMemoryInvestigationStore


def _trigger(**labels: str) -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title="test",
        payload={"status": "firing", "alerts": [{"labels": dict(labels)}]},
    )


def _finding(agent: str = "argus", kind: FindingKind = FindingKind.ANOMALY) -> Finding:
    return Finding(
        id=uuid4(),
        agent=agent,
        kind=kind,
        title="something moved",
        severity=Severity.MEDIUM,
        confidence=0.5,
        detected_at=datetime.now(UTC),
        evidence=[] if kind is FindingKind.DEGRADED else [_evidence()],
        tags=["metric:memory"],
    )


def _evidence() -> Any:
    from core.contracts.evidence import Evidence, EvidenceSource, MetricWindowPayload

    return Evidence(
        id=uuid4(),
        source=EvidenceSource(connector="prometheus", query="up"),
        observed_at=datetime.now(UTC),
        summary="pod-7 moved",
        payload=MetricWindowPayload(metric="up"),
    )


# --- classification reads, it does not guess ---------------------------------


def test_a_scenario_label_is_read_not_inferred() -> None:
    result = classify(_trigger(scenario="bad_deploy_5xx", severity="critical"))
    assert result.domain == "anomaly"
    assert result.severity is Severity.CRITICAL
    assert result.certain is True
    assert "bad_deploy_5xx" in result.reason


def test_an_unlabelled_trigger_is_routed_but_not_confidently() -> None:
    """Routing to the only implemented domain is not the same as classifying.

    The distinction has to survive into the plan, because "we know this is a
    metric problem" and "this is the only thing that runs" produce the same
    dispatch and mean different things.
    """
    result = classify(_trigger())
    assert result.certain is False
    assert "not determined" in result.reason

    step = planner.build(result)[0]
    assert "NOT determined" in step.reason, (
        "the plan hides the classifier's uncertainty, so a reviewer sees a "
        "confident routing decision that nobody made"
    )


def test_an_unknown_severity_lands_on_medium_rather_than_guessing() -> None:
    assert classify(_trigger(severity="apocalyptic")).severity is Severity.MEDIUM


def test_the_scenario_is_kept_so_a_run_can_be_scored() -> None:
    assert scenario_of(_trigger(scenario="memory_leak")) == "memory_leak"
    assert scenario_of(_trigger()) is None


# --- the planner will not plan a stub ----------------------------------------


def test_only_implemented_agents_are_planned() -> None:
    """Every domain has a manifest. Only one has an implementation.

    Planning from the manifest roster would dispatch nine agents that raise
    `NotImplementedError`, and the run would fail for a reason that has nothing
    to do with the incident.
    """
    rostered = {manifest.domain for manifest in loader.load_all().values()}
    assert set(planner.IMPLEMENTED) < rostered, (
        "IMPLEMENTED should be a strict subset of the roster; if they are equal, "
        "either every agent is built or this set has stopped being checked"
    )

    for domain in rostered - set(planner.IMPLEMENTED):
        with pytest.raises(planner.NoAgentForDomain, match="no implemented agent"):
            planner.build(Classification(domain, Severity.MEDIUM, True, "test"))


def test_a_plan_step_says_why_it_exists() -> None:
    step = planner.build(classify(_trigger(alertname="NodeDiskFillingUp")))[0]
    assert step.agent == "argus"
    assert step.reason, "a step with no reason cannot be reviewed"
    assert step.status is StepStatus.PENDING


# --- the verdict is an aggregation, not a diagnosis --------------------------


def test_the_verdict_proposes_no_hypotheses() -> None:
    """The load-bearing assertion of this whole file.

    Argus detects. Nothing here ranks candidate causes, and a Verdict that
    invented one would be scored against `simulator/scenarios/*.yaml` ground
    truth as though it were reasoning.
    """
    steps = planner.build(classify(_trigger(scenario="memory_leak")))
    done = [steps[0].model_copy(update={"status": StepStatus.COMPLETE})]
    verdict = aggregator.aggregate(uuid4(), [_finding(), _finding()], done)

    assert verdict.hypotheses == [], (
        "a detector's output is not an explanation; proposing one here would be "
        "inventing the step between 'this moved' and 'this is why'"
    )
    assert verdict.confidence == 0.0, "confidence is in the leading hypothesis, and there is none"
    assert len(verdict.contributing_findings) == 2
    assert verdict.steps == done, "a verdict without its steps cannot tell nobody-looked apart"
    assert "not an explanation" in verdict.summary


def test_a_verdict_over_no_findings_does_not_claim_health() -> None:
    steps = [
        planner.build(classify(_trigger()))[0].model_copy(update={"status": StepStatus.COMPLETE})
    ]
    verdict = aggregator.aggregate(uuid4(), [], steps)
    assert "no metric crossed" in verdict.summary
    assert "healthy" not in verdict.summary.lower()


def test_a_verdict_over_nothing_dispatched_says_so() -> None:
    """Never-dispatched and found-nothing must not read the same."""
    pending = planner.build(classify(_trigger()))
    verdict = aggregator.aggregate(uuid4(), [], pending)
    assert "nothing was looked at" in verdict.summary
    assert "not a finding" in verdict.summary.lower()


def test_a_blind_run_does_not_report_a_quiet_one() -> None:
    """The bug this test was written against, and found.

    The first summary said "no metric crossed its calibrated threshold" in the
    same sentence as the failure - so a run where Argus could not reach
    Prometheus read as a run where nothing was wrong. An agent that could not
    look has established nothing about what it did not see.
    """
    steps = [
        planner.build(classify(_trigger()))[0].model_copy(update={"status": StepStatus.DEGRADED})
    ]
    verdict = aggregator.aggregate(uuid4(), [_finding(kind=FindingKind.DEGRADED)], steps)

    assert verdict.partial is True
    assert "no metric crossed" not in verdict.summary, (
        f"a degraded run claimed a clean result: {verdict.summary}"
    )
    assert "could not complete" in verdict.summary
    assert "not a quiet cluster" in verdict.summary


# --- the run, end to end, offline --------------------------------------------


class _Quiet(BaseAgent):
    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return []


class _Noisy(BaseAgent):
    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return [_finding()]


class _Blind(BaseAgent):
    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        raise AgentDegraded("prometheus is unreachable", retryable=True)


@pytest.fixture
def registered() -> Any:
    original = dict(dispatcher.AGENTS)
    yield dispatcher.AGENTS
    dispatcher.AGENTS.clear()
    dispatcher.AGENTS.update(original)


@pytest.mark.asyncio
async def test_a_run_emits_its_lifecycle_in_order(registered: Any) -> None:
    dispatcher.register("argus", _Noisy)
    bus, store = InMemoryEventBus(), InMemoryInvestigationStore()

    investigation = await investigate(_trigger(scenario="memory_leak"), store=store, bus=bus)

    emitted = [e.event.type for e in bus.published]
    assert emitted == [
        "investigation_started",
        "step_started",
        "step_finished",
        "verdict_ready",
        "investigation_completed",
    ], emitted
    assert investigation.state is InvestigationState.COMPLETED
    assert investigation.scenario == "memory_leak"


@pytest.mark.asyncio
async def test_the_investigation_is_saved_before_it_is_announced(registered: Any) -> None:
    """An event about a run nobody can fetch is worse than a late event."""
    dispatcher.register("argus", _Quiet)
    store = InMemoryInvestigationStore()

    seen: list[bool] = []

    class _Watching(InMemoryEventBus):
        async def publish(self, event: Any, *, investigation_id: UUID | None = None) -> Any:
            if event.type == "investigation_started" and investigation_id:
                seen.append(await store.get(investigation_id) is not None)
            return await super().publish(event, investigation_id=investigation_id)

    await investigate(_trigger(), store=store, bus=_Watching())
    assert seen == [True], "the start event was published before the row existed"


@pytest.mark.asyncio
async def test_a_degraded_agent_produces_a_completed_partial_run(registered: Any) -> None:
    """Zeus completing and the agent failing are different facts."""
    dispatcher.register("argus", _Blind)
    bus, store = InMemoryEventBus(), InMemoryInvestigationStore()

    investigation = await investigate(_trigger(), store=store, bus=bus)

    assert investigation.state is InvestigationState.COMPLETED
    assert investigation.plan[0].status is StepStatus.DEGRADED
    assert investigation.verdict is not None and investigation.verdict.partial is True
    completed = [e.event for e in bus.published if isinstance(e.event, InvestigationCompletedEvent)]
    assert completed and completed[0].partial is True


@pytest.mark.asyncio
async def test_the_id_the_receiver_returned_is_the_id_that_persists(registered: Any) -> None:
    """A 202 that hands back an id nothing creates is a promise nobody keeps."""
    dispatcher.register("argus", _Quiet)
    store = InMemoryInvestigationStore()
    promised = uuid4()

    investigation = await investigate(
        _trigger(), store=store, bus=InMemoryEventBus(), investigation_id=promised
    )

    assert investigation.id == promised
    assert await store.get(promised) is not None


@pytest.mark.asyncio
async def test_an_unregistered_agent_is_a_distinct_failure(registered: Any) -> None:
    dispatcher.AGENTS.clear()
    with pytest.raises(dispatcher.AgentNotDispatchable, match="not an implementation"):
        await investigate(_trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus())
