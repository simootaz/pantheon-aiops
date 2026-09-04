"""Zeus: what it plans, what it dispatches, and what its Verdict refuses to claim.

The live gate is `tests/integration/test_flow_one.py`. These are the properties
that need no stack.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from core import orchestrator
from core.bus import InMemoryEventBus
from core.contracts.events import InvestigationCompletedEvent
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import InvestigationState, Trigger, TriggerKind
from core.contracts.plan import StepStatus
from core.contracts.root_cause import RootCauseCategory
from core.orchestrator import aggregator, classifier, dispatcher, planner
from core.orchestrator.classifier import Classification, classify, scenario_of
from core.orchestrator.router import get as orchestrator_get
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


def _a_question(question: str) -> Trigger:
    """What a human asking Pantheon something looks like."""
    return Trigger(
        kind=TriggerKind.HUMAN_QUESTION,
        received_at=datetime.now(UTC),
        source="dashboard",
        title=question,
        payload={"question": question},
    )


def _a_pull_request(number: int = 12, repository: str = "acme/checkout") -> Trigger:
    """What GitHub sends when somebody opens a pull request."""
    return Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=datetime.now(UTC),
        source="github",
        title=f"pull request #{number}",
        payload={
            "action": "opened",
            "pull_request": {"number": number},
            "repository": {"full_name": repository},
        },
    )


def _a_failed_run(
    run_id: int = 99, conclusion: str = "failure", repository: str = "acme/checkout"
) -> Trigger:
    """What GitHub sends when a workflow run completes."""
    return Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=datetime.now(UTC),
        source="github",
        title=f"workflow run {run_id}",
        payload={
            "action": "completed",
            "workflow_run": {"id": run_id, "conclusion": conclusion},
            "repository": {"full_name": repository},
        },
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


def _named(which: str) -> Finding:
    """A Finding carrying a metric the ranker IS entitled to conclude from."""
    from core.contracts.evidence import Evidence, EvidenceSource, MetricWindowPayload, ResourceRef

    metric = {
        "memory": "pantheon_pod_memory_working_set_bytes",
        "disk": "pantheon_node_disk_used_bytes / pantheon_node_disk_total_bytes",
    }[which]
    subject = ResourceRef(kind="pod" if which == "memory" else "node", name=f"{which}-1")
    return Finding(
        id=uuid4(),
        agent="argus",
        kind=FindingKind.ANOMALY,
        title=f"{metric} crossed",
        severity=Severity.MEDIUM,
        confidence=0.5,
        detected_at=datetime.now(UTC),
        subject=subject,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query=metric),
                observed_at=datetime.now(UTC),
                summary=f"{metric} crossed",
                subject=subject,
                payload=MetricWindowPayload(metric=metric),
            )
        ],
    )


def _resolution_record() -> Any:
    from core.contracts.llm import (
        ModelDescriptor,
        ModelRequirements,
        ResolutionRecord,
        ResolutionStep,
    )

    return ResolutionRecord(
        id=uuid4(),
        requested_by="argus",
        requirements=ModelRequirements(),
        matched_step=ResolutionStep.TIER_DEFAULT,
        chosen=ModelDescriptor(provider_id="p", model_id="balanced"),
        resolved_at=datetime.now(UTC),
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
    assert result.domains == ("anomaly", "log_clustering")
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
            planner.build(Classification((domain,), Severity.MEDIUM, True, "test"))


def test_a_plan_step_says_why_it_exists() -> None:
    step = planner.build(classify(_trigger(alertname="NodeDiskFillingUp")))[0]
    assert step.agent == "argus"
    assert step.reason, "a step with no reason cannot be reviewed"
    assert step.status is StepStatus.PENDING


# --- the verdict is an aggregation, not a diagnosis --------------------------


def test_a_metric_nothing_declared_an_entitlement_for_cannot_name_a_cause() -> None:
    """The load-bearing assertion of this whole file, and it survived the
    ranker landing.

    These Findings carry the metric `up`, which `core/orchestrator/hypotheses.py`
    declares nothing about. The Verdict must come back UNKNOWN - not silent, and
    above all not carrying an invented category, which would be scored against
    `simulator/scenarios/*.yaml` ground truth as though it were reasoning.
    """
    steps = planner.build(classify(_trigger(scenario="memory_leak")))
    done = [steps[0].model_copy(update={"status": StepStatus.COMPLETE})]
    verdict = aggregator.aggregate(uuid4(), [_finding(), _finding()], done)

    (hypothesis,) = verdict.hypotheses
    assert hypothesis.category is RootCauseCategory.UNKNOWN, (
        "an unrecognised metric named a cause; a detector's output is not an "
        "explanation and the mapping must be a decision somebody made"
    )
    assert verdict.confidence == hypothesis.confidence
    assert len(verdict.contributing_findings) == 2
    assert verdict.steps == done, "a verdict without its steps cannot tell nobody-looked apart"
    assert "not an explanation" in verdict.summary


def test_two_tied_hypotheses_leave_the_verdict_at_zero_confidence() -> None:
    """A tie is a run that reached no conclusion. Reporting the best score would
    present a coin flip as a finding."""
    steps = planner.build(classify(_trigger(scenario="memory_leak")))
    done = [steps[0].model_copy(update={"status": StepStatus.COMPLETE})]

    verdict = aggregator.aggregate(uuid4(), [_named("memory"), _named("disk")], done)

    assert len(verdict.hypotheses) == 2
    assert verdict.confidence == 0.0


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


class _QuietLethe(BaseAgent):
    """A second agent in a DIFFERENT domain.

    `_Quiet` is `anomaly`, so registering it twice makes every accounting entry
    say `argus` and any per-agent assertion tests the fixture rather than the
    attribution.
    """

    domain = "log_clustering"

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
    dispatcher.register("lethe", _Quiet)
    bus, store = InMemoryEventBus(), InMemoryInvestigationStore()

    investigation = await investigate(_trigger(scenario="memory_leak"), store=store, bus=bus)

    emitted = [e.event.type for e in bus.published]
    # Two step pairs: an alert is read with metrics AND logs, so the plan has
    # two steps. Written out rather than counted, because the ORDER is what this
    # asserts - a verdict emitted before a step finished would be a verdict over
    # findings that had not arrived.
    assert emitted == [
        "investigation_started",
        "step_started",
        "step_finished",
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
    dispatcher.register("lethe", _Quiet)
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
    dispatcher.register("lethe", _Quiet)
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
    dispatcher.register("lethe", _Quiet)
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


@pytest.mark.asyncio
async def test_an_unroutable_trigger_is_recorded_as_failed_before_it_raises(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run nobody could plan must not vanish.

    The caller gets the exception, but the reason has to survive somewhere a
    reader can find it - otherwise an unroutable alert is indistinguishable from
    one that never arrived.
    """
    dispatcher.register("argus", _Quiet)
    dispatcher.register("lethe", _Quiet)
    monkeypatch.setattr(planner, "IMPLEMENTED", {})
    bus, store = InMemoryEventBus(), InMemoryInvestigationStore()

    with pytest.raises(planner.NoAgentForDomain, match="no implemented agent"):
        await investigate(_trigger(), store=store, bus=bus)

    saved = await store.recent()
    assert len(saved) == 1, "the unroutable run left no record"
    assert saved[0].state is InvestigationState.FAILED
    assert saved[0].completed_at is not None, "a terminal state with no completion time"

    completed = [e.event for e in bus.published if isinstance(e.event, InvestigationCompletedEvent)]
    assert completed and completed[0].partial is True, (
        "a run that never dispatched anything is partial by definition"
    )
    assert not any(e.event.type == "investigation_started" for e in bus.published), (
        "a run that could not be planned announced itself as started"
    )


@pytest.mark.asyncio
async def test_reading_one_back_returns_it_or_none(registered: Any) -> None:
    """`get` is the read side of the same store the API uses."""
    dispatcher.register("argus", _Quiet)
    dispatcher.register("lethe", _Quiet)
    store = InMemoryInvestigationStore()
    investigation = await investigate(_trigger(), store=store, bus=InMemoryEventBus())

    assert (await orchestrator_get(investigation.id, store=store)) is not None
    assert (await orchestrator_get(uuid4(), store=store)) is None


@pytest.mark.asyncio
async def test_a_model_consultation_persists_on_the_investigation(registered: Any) -> None:
    """`Investigation.resolutions` is what answers "which model answered, and why".

    Zeus collects them from the outcome rather than the agent writing them
    anywhere, so an agent cannot forget - and the store persists the whole
    Investigation, so they travel with it without a second write path.
    """

    class _Consulting(BaseAgent):
        domain = "anomaly"

        async def investigate(self, ctx: AgentContext) -> list[Finding]:
            ctx.resolutions.append(_resolution_record())
            return [_finding()]

    dispatcher.register("argus", _Consulting)
    dispatcher.register("lethe", _Quiet)
    store = InMemoryInvestigationStore()

    investigation = await investigate(_trigger(), store=store, bus=InMemoryEventBus())

    assert len(investigation.resolutions) == 1
    assert investigation.resolutions[0].requested_by == "argus"
    stored = await store.get(investigation.id)
    assert stored is not None and len(stored.resolutions) == 1, (
        "the resolution did not survive being stored"
    )


@pytest.mark.asyncio
async def test_a_degraded_run_still_records_what_it_spent(registered: Any) -> None:
    """The runs anybody asks about are the ones that went wrong.

    A record that only survives a successful run cannot answer "what did this
    cost" for the failures - and an agent that degraded halfway still consulted
    a model and still spent the money.
    """

    class _ConsultsThenFails(BaseAgent):
        domain = "anomaly"

        async def investigate(self, ctx: AgentContext) -> list[Finding]:
            ctx.resolutions.append(_resolution_record())
            raise AgentDegraded("prometheus went away after the model answered")

    dispatcher.register("argus", _ConsultsThenFails)
    dispatcher.register("lethe", _Quiet)
    investigation = await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus()
    )

    assert investigation.plan[0].status is StepStatus.DEGRADED
    assert len(investigation.resolutions) == 1, (
        "a degraded run lost the record of the model it had already paid for"
    )


# --- what the planner promises, the dispatcher must be able to deliver -----------


def test_every_implemented_agent_is_actually_registered() -> None:
    """`IMPLEMENTED` is a promise the dispatcher has to keep.

    The planner reads it to decide what a plan may contain; the dispatcher reads
    AGENTS to decide what can run. Nothing tied the two together, so an entry
    added to one and forgotten in the other produced a plan naming an agent that
    raises `AgentNotDispatchable` at dispatch - discovered during an
    investigation rather than at import.

    Found by planting exactly that: `lethe` in IMPLEMENTED, never registered,
    and the whole suite stayed green.
    """
    orchestrator.register_implemented()

    missing = sorted(set(planner.IMPLEMENTED.values()) - set(dispatcher.AGENTS))
    assert not missing, (
        f"planner.IMPLEMENTED names {missing}, which register_implemented() does not "
        "register. A plan would name them and dispatch would refuse."
    )


def test_nothing_is_registered_that_the_planner_will_never_name() -> None:
    """The other direction. A registered agent no plan reaches is dead code that
    looks live - and the way it is usually discovered is someone assuming it ran."""
    orchestrator.register_implemented()

    orphaned = sorted(set(dispatcher.AGENTS) - set(planner.IMPLEMENTED.values()))
    assert not orphaned, (
        f"{orphaned} are dispatchable but no domain in IMPLEMENTED maps to them, "
        "so no plan can ever name one."
    )


def test_every_implemented_domain_has_a_manifest_declaring_that_domain() -> None:
    """The third leg. A codename in IMPLEMENTED with no manifest, or one whose
    manifest claims a different domain, plans fine and binds no tools."""
    for domain, codename in sorted(planner.IMPLEMENTED.items()):
        manifest = loader.for_codename(codename)
        assert manifest.domain == domain, (
            f"IMPLEMENTED maps {domain!r} to {codename!r}, but that manifest "
            f"declares domain {manifest.domain!r}"
        )


def test_every_implemented_agent_can_reach_the_tools_it_declares() -> None:
    """A declared tool with no implementation makes ToolNotBound the NORMAL case.

    The connector guards check this per connector; nothing checked it per
    dispatchable agent. Hermes declared `kubernetes.list` and `kubernetes.get`,
    which exist in no language - the Go connector's read-only tool list is
    scaffolding and its python_ref is a six-line stub - and the whole suite was
    green. An agent would have planned, dispatched, and failed at call time.

    Only agents in IMPLEMENTED are checked. A stub agent's manifest is a
    statement of intent, and holding intent to this standard would mean
    deleting the roadmap.
    """
    adapters = {
        "argus": "agents.anomaly.tools",
        "aegis": "agents.manifest_review.tools",
        "hephaestus": "agents.ci_triage.tools",
        "lethe": "agents.log_clustering.tools",
        "hermes": "agents.nl_query.tools",
    }

    for codename in sorted(planner.IMPLEMENTED.values()):
        assert codename in adapters, (
            f"{codename} is dispatchable and this check does not know where its "
            "tool implementations live. Add it, or the agent is unchecked."
        )
        module = import_module(adapters[codename])
        declared = set(loader.for_codename(codename).tools)
        implemented = set(module.IMPLEMENTATIONS)

        assert declared == implemented, (
            f"{codename} declares {sorted(declared - implemented)} with no "
            f"implementation, and implements {sorted(implemented - declared)} "
            "that its manifest does not declare."
        )


def test_every_implemented_agent_is_reachable_by_some_trigger() -> None:
    """Registered is not the same as reachable, and this is the difference.

    Lethe and Hermes were implemented, registered and dispatchable for days
    while `classify()` could only ever return `anomaly`. Every existing guard
    passed: the manifests were valid, the tools matched, the registry was
    complete. Nothing routed to them and nothing said so.

    `test_every_implemented_agent_is_actually_registered` checks the planner
    against the dispatcher. This checks the CLASSIFIER against the planner - the
    step before, which is where the gap was.
    """
    reachable: set[str] = set()
    for trigger in (
        _trigger(alertname="NodeDiskFillingUp"),
        _trigger(scenario="memory_leak"),
        _trigger(),
        _a_question("what is the error rate?"),
        _a_pull_request(),
        _a_failed_run(),
    ):
        reachable.update(classify(trigger).domains)

    unreachable = sorted(set(planner.IMPLEMENTED) - reachable)
    assert not unreachable, (
        f"{unreachable} have implemented agents that no trigger can route to. They "
        "are registered and dispatchable and nothing will ever dispatch them - which "
        "reads, from every other guard, as working."
    )


def test_a_question_goes_to_hermes_and_not_to_a_window_scanner() -> None:
    """Argus and Lethe scan a window and report what moved. Neither answers
    "what is the error rate right now", and pointing them at a question produces
    findings nobody asked for."""
    classification = classify(_a_question("what is the error rate?"))

    assert classification.domains == ("nl_query",)
    assert classification.certain


def test_an_alert_carrying_a_question_shaped_field_is_still_an_alert() -> None:
    """Read from the trigger KIND, not from a payload key.

    Alertmanager annotations are operator-supplied text. A payload key alone
    would let anyone route an alert to Hermes by naming a field `question`.
    """
    trigger = _trigger(alertname="NodeDiskFillingUp")
    trigger.payload["question"] = "what is the error rate?"

    assert classify(trigger).domains == ("anomaly", "log_clustering")


def test_a_domain_with_no_agent_is_skipped_rather_than_failing_the_plan() -> None:
    """An unimplemented agent must not block the implemented ones."""
    mixed = Classification(("anomaly", "knowledge"), Severity.MEDIUM, True, "test")

    steps = planner.build(mixed)

    assert [step.agent for step in steps] == ["argus"]
    assert "knowledge" in steps[0].reason, (
        "the skipped domain is not named on the plan, so a reader cannot see what was not looked at"
    )


def test_the_skip_note_is_the_same_on_every_step() -> None:
    """Accumulating skips inside the loop put a different reason on each step
    depending on where the stub fell in the order - a plan that reads as though
    the omission happened partway through."""
    mixed = Classification(
        ("anomaly", "knowledge", "log_clustering"), Severity.MEDIUM, True, "test"
    )

    reasons = {step.reason for step in planner.build(mixed)}

    assert len(reasons) == 1, f"steps disagree about why: {reasons}"


@pytest.mark.asyncio
async def test_an_investigation_records_what_each_agent_consumed(registered: Any) -> None:
    """One entry per dispatched step. Without it the token meter can stop a run
    and leave nothing behind saying why it was expensive."""
    dispatcher.register("argus", _Quiet)
    dispatcher.register("lethe", _QuietLethe)

    investigation = await investigate(
        _trigger(scenario="memory_leak"),
        store=InMemoryInvestigationStore(),
        bus=InMemoryEventBus(),
    )

    assert [entry.agent for entry in investigation.accounting] == ["argus", "lethe"]
    assert all(entry.token_ceiling > 0 for entry in investigation.accounting), (
        "an accounting entry with no ceiling cannot answer whether the spend was close"
    )


# --- a webhook is about one thing, and that thing reaches the agent ---------------------


def test_a_pull_request_is_reviewed_rather_than_investigated() -> None:
    """Nothing has happened yet. There is no window to scan and no incident to
    explain, so pointing Argus and Lethe at a pull request would have them
    report on whatever the cluster was doing while somebody opened it."""
    classification = classify(_a_pull_request())

    assert classification.domains == ("manifest_review",)
    assert classification.certain


def test_a_failed_workflow_run_is_triaged() -> None:
    """The failure is in the pipeline, not the cluster, and a metric scan over
    the minutes around it reports the weather rather than the fault."""
    classification = classify(_a_failed_run())

    assert classification.domains == ("ci_triage",)


def test_a_green_workflow_run_starts_no_investigation() -> None:
    """GitHub sends `workflow_run` for every completion. Starting an
    investigation for every green build is how a system teaches people to
    ignore it."""
    classification = classify(_a_failed_run(conclusion="success"))

    assert classification.domains != ("ci_triage",)


def test_a_cancelled_run_is_not_triaged_either() -> None:
    """A cancelled run says somebody pushed again."""
    assert classify(_a_failed_run(conclusion="cancelled")).domains != ("ci_triage",)


def test_an_alert_carrying_a_field_called_pull_request_is_still_an_alert() -> None:
    """The trigger KIND is checked as well as the payload - the same rule
    `question_of` follows. Alertmanager annotations are operator-supplied text,
    and a payload key alone would let one route to Aegis."""
    hostile = Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title="CheckoutErrorRateHigh",
        payload={
            "pull_request": {"number": 1},
            "repository": {"full_name": "acme/checkout"},
            "labels": {"alertname": "CheckoutErrorRateHigh"},
        },
    )

    assert classify(hostile).domains == classifier.ALERT_DOMAINS


def test_a_webhook_with_no_repository_routes_nowhere_new() -> None:
    """Every tool the change and CI agents call takes a repository, and one
    guessed from a URL or a title would send a read at the wrong project -
    which answers, plausibly, about something else."""
    nameless = Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=datetime.now(UTC),
        source="github",
        title="pull request #12",
        payload={"pull_request": {"number": 12}},
    )

    assert classify(nameless).domains != ("manifest_review",)


def test_the_subject_of_an_alert_is_empty() -> None:
    """Argus and Lethe take a window, and the window is on the context already.
    Params invented for them would be params nothing reads."""
    assert classifier.subject_of(_trigger(alertname="X")) == {}


def test_the_subject_of_a_pull_request_is_what_aegis_needs() -> None:
    """One reader of the payload, not two. A classifier that answered "yes, a
    pull request" and left the extraction to a dispatcher would be two readers
    of one payload, and the one that drifts is the one nobody tests."""
    assert classifier.subject_of(_a_pull_request(number=7, repository="acme/api")) == {
        "repository": "acme/api",
        "pull_request": 7,
    }


def test_the_subject_of_a_failed_run_is_what_hephaestus_needs() -> None:
    subject = classifier.subject_of(_a_failed_run(run_id=42))

    assert subject["repository"] == "acme/checkout"
    assert subject["run"] == 42


@pytest.mark.asyncio
async def test_the_subject_reaches_the_agent_as_params() -> None:
    """The end of the chain. Without this the two agents are registered,
    planned, dispatched - and degrade with "no run was named", which reads as a
    broken agent rather than as a missing route."""
    seen: dict[str, Any] = {}

    class _Recorder(BaseAgent):
        domain = "ci_triage"

        async def investigate(self, ctx: AgentContext) -> list[Finding]:
            seen.update(ctx.params)
            return []

    from core.orchestrator.dispatcher import register

    register("hephaestus", _Recorder)
    try:
        trigger = _a_failed_run(run_id=77)
        step = planner.build(classify(trigger))[0]
        now = datetime.now(UTC)
        await dispatcher.run_step(
            step,
            investigation_id=uuid4(),
            trigger=trigger,
            window_start=now - timedelta(minutes=10),
            window_end=now,
        )
    finally:
        from agents.ci_triage.agent import Hephaestus

        register("hephaestus", Hephaestus)  # restore, or every later test sees the stub

    assert seen == {"repository": "acme/checkout", "run": 77, "conclusion": "failure"}
