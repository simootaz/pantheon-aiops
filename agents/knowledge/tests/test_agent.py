"""Mnemosyne: what "the same alert on the same thing" means, and where history goes.

Three seams, each tested where it is:

- `recall.matches` on triggers, because "same" has edge cases a run never
  produces - a pod-level alert against a service-level prior, a prior with no
  alertname, another tenant's identical alert.
- The agent through `investigate()` with a real InMemoryInvestigationStore,
  because the tool is provided by the runtime and a test that handed the agent
  a fake would pass with the provisioning broken.
- `hypotheses.rank`, because the one thing history must never do is raise
  confidence in the present.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from agents._base.base_agent import AgentContext, BaseAgent
from agents.knowledge.agent import MAX_LISTED, Mnemosyne
from core.bus import InMemoryEventBus
from core.contracts.evidence import EvidenceKind
from core.contracts.finding import FindingKind
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.contracts.root_cause import HypothesisStatus, RootCauseCategory, RootCauseHypothesis
from core.contracts.verdict import Verdict
from core.memory.recall import SUBJECT_KEYS, alert_key, matches, priors_of
from core.orchestrator import dispatcher
from core.orchestrator.router import investigate
from core.store.investigations import InMemoryInvestigationStore

NOW = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


def _alert(**labels: str) -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=NOW,
        source="alertmanager",
        title="t",
        payload={"status": "firing", "alerts": [{"labels": dict(labels)}]},
    )


def _verdict(investigation_id: UUID, category: RootCauseCategory, confidence: float) -> Verdict:
    return Verdict(
        id=uuid4(),
        investigation_id=investigation_id,
        summary="s",
        hypotheses=[
            RootCauseHypothesis(
                id=uuid4(),
                category=category,
                statement="x",
                status=HypothesisStatus.PROPOSED,
                confidence=confidence,
                proposed_by="zeus",
            )
        ],
        confidence=confidence,
        decided_at=NOW,
        steps=[],
    )


def _prior(
    trigger: Trigger,
    *,
    days_ago: float,
    tenant: str = "default",
    category: RootCauseCategory | None = RootCauseCategory.MEMORY_LEAK,
    confidence: float = 0.65,
) -> Investigation:
    identifier = uuid4()
    created = NOW - timedelta(days=days_ago)
    return Investigation(
        id=identifier,
        state=InvestigationState.COMPLETED,
        trigger=trigger,
        created_at=created,
        completed_at=created + timedelta(minutes=2),
        tenant=tenant,
        verdict=_verdict(identifier, category, confidence) if category is not None else None,
    )


# --- what "same" means ----------------------------------------------------------------


def test_the_same_alert_on_the_same_pod_matches() -> None:
    now = _alert(alertname="PodRestarting", pod="checkout-7f9", namespace="shop")
    before = _alert(alertname="PodRestarting", pod="checkout-7f9", namespace="shop")

    assert matches(now, before)


def test_the_same_alert_on_a_different_pod_does_not() -> None:
    """The control. A matcher on alertname alone would report every pod's
    history against this one."""
    now = _alert(alertname="PodRestarting", pod="checkout-7f9")
    other = _alert(alertname="PodRestarting", pod="checkout-2c1")

    assert not matches(now, other)


def test_a_service_level_prior_does_not_answer_a_pod_level_alert() -> None:
    """Every key the CURRENT alert carries must be present on the prior. A
    pod-level alert and a service-level alert with one name are two questions,
    and folding them would report a service's history against one pod."""
    now = _alert(alertname="HighErrorRate", service="checkout", pod="checkout-7f9")
    service_wide = _alert(alertname="HighErrorRate", service="checkout")

    assert not matches(now, service_wide)


def test_extra_keys_on_the_prior_are_ignored() -> None:
    """Asked from the current alert's side. A prior that also carried a node
    label is still the same alert on the same pod."""
    now = _alert(alertname="PodRestarting", pod="checkout-7f9")
    more_specific = _alert(alertname="PodRestarting", pod="checkout-7f9", node="node-a")

    assert matches(now, more_specific)


def test_a_prior_that_is_not_an_alert_never_matches() -> None:
    """A webhook carrying a `labels` key is not an alert, whatever it says."""
    now = _alert(alertname="PodRestarting", pod="checkout-7f9")
    webhook = Trigger(
        kind=TriggerKind.WEBHOOK,
        received_at=NOW,
        source="github",
        title="t",
        payload={"labels": {"alertname": "PodRestarting", "pod": "checkout-7f9"}},
    )

    assert not matches(now, webhook)


def test_an_alert_with_no_name_has_no_key_and_matches_nothing() -> None:
    """Matching on nothing would make every prior a match."""
    nameless = _alert(pod="checkout-7f9")

    assert alert_key(nameless) is None
    assert not matches(nameless, _alert(pod="checkout-7f9"))


def test_the_subject_keys_are_the_ones_alertmanager_actually_sets() -> None:
    assert set(SUBJECT_KEYS) == {"pod", "service", "node", "instance", "namespace"}


def test_priors_exclude_the_current_run_and_come_newest_first() -> None:
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    current = _prior(trigger, days_ago=0, category=None)
    older = _prior(trigger, days_ago=5)
    newer = _prior(trigger, days_ago=1)

    found = priors_of(current, [current, older, newer])

    assert [p.investigation_id for p in found] == [newer.id, older.id]


# --- the agent, through the runtime -------------------------------------------------


@pytest.fixture
def only_mnemosyne() -> Any:
    original = dict(dispatcher.AGENTS)
    dispatcher.AGENTS.clear()

    class _Quiet(BaseAgent):
        domain = "anomaly"

        async def investigate(self, ctx: AgentContext) -> list[Any]:
            return []

    class _QuietLethe(_Quiet):
        domain = "log_clustering"

    class _QuietMoira(_Quiet):
        domain = "capacity"

    dispatcher.register("argus", _Quiet)
    dispatcher.register("lethe", _QuietLethe)
    dispatcher.register("moira", _QuietMoira)
    dispatcher.register("mnemosyne", Mnemosyne)
    yield
    dispatcher.AGENTS.clear()
    dispatcher.AGENTS.update(original)


def _recall_finding(investigation: Investigation) -> Any:
    found = [f for f in investigation.findings if f.agent == "mnemosyne"]
    return found[0] if found else None


@pytest.mark.asyncio
async def test_a_recurrence_is_reported_with_what_was_concluded(only_mnemosyne: Any) -> None:
    """The whole point: "this has happened before, and last time we said X"."""
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9", namespace="shop")
    store = InMemoryInvestigationStore()
    await store.save(_prior(trigger, days_ago=3))
    await store.save(_prior(trigger, days_ago=1, confidence=0.75))

    run = await investigate(trigger, store=store, bus=InMemoryEventBus())
    finding = _recall_finding(run)

    assert finding is not None
    assert finding.kind is FindingKind.OBSERVATION
    assert "2 times before" in finding.title
    assert "memory_leak at 0.75" in finding.title, finding.title
    assert len(finding.evidence) == 2
    assert all(e.kind is EvidenceKind.PRIOR_INCIDENT for e in finding.evidence)
    assert finding.evidence[0].payload.confidence == 0.75, "newest first"


@pytest.mark.asyncio
async def test_a_first_occurrence_produces_no_finding(only_mnemosyne: Any) -> None:
    """The control. "No history" is what the step's clean completion says; a
    Finding saying it would be an agent that found nothing reporting that it
    found nothing, in a list meant for things found."""
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    store = InMemoryInvestigationStore()
    await store.save(_prior(_alert(alertname="PodRestarting", pod="checkout-2c1"), days_ago=1))

    run = await investigate(trigger, store=store, bus=InMemoryEventBus())

    assert _recall_finding(run) is None
    (step,) = [s for s in run.plan if s.agent == "mnemosyne"]
    assert step.status.value == "complete"


@pytest.mark.asyncio
async def test_the_run_being_investigated_is_not_its_own_prior(only_mnemosyne: Any) -> None:
    """The current row is saved before the agents run. It is not a recurrence."""
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")

    run = await investigate(trigger, store=InMemoryInvestigationStore(), bus=InMemoryEventBus())

    assert _recall_finding(run) is None


@pytest.mark.asyncio
async def test_another_tenants_identical_alert_is_not_recalled(only_mnemosyne: Any) -> None:
    """The tenant is fixed by the runtime from the run in progress; the tool
    has no parameter for another one. Existence is the disclosure."""
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    store = InMemoryInvestigationStore()
    await store.save(_prior(trigger, days_ago=1, tenant="globex"))

    run = await investigate(trigger, store=store, bus=InMemoryEventBus(), tenant="acme")

    assert _recall_finding(run) is None


@pytest.mark.asyncio
async def test_a_prior_that_reached_no_conclusion_is_reported_as_such(
    only_mnemosyne: Any,
) -> None:
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    store = InMemoryInvestigationStore()
    await store.save(_prior(trigger, days_ago=1, category=None))

    finding = _recall_finding(await investigate(trigger, store=store, bus=InMemoryEventBus()))

    assert finding is not None
    assert "reached no conclusion" in finding.title
    assert finding.evidence[0].payload.category is None


@pytest.mark.asyncio
async def test_many_recurrences_are_counted_and_the_newest_listed(only_mnemosyne: Any) -> None:
    """A title that says 12 and evidence that lists 5 is a Finding a reader
    can size without expanding."""
    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    store = InMemoryInvestigationStore()
    for days in range(12):
        await store.save(_prior(trigger, days_ago=days + 1))

    finding = _recall_finding(await investigate(trigger, store=store, bus=InMemoryEventBus()))

    assert finding is not None
    assert "12 times before" in finding.title
    assert len(finding.evidence) == MAX_LISTED
    assert "recurrences:12" in finding.tags


@pytest.mark.asyncio
async def test_without_a_store_the_tool_is_unbound_and_the_step_degrades() -> None:
    """No store, no tool. `ToolNotBound` reads as "not available", which is
    honest; a Finding saying "no history" would not be."""
    agent = Mnemosyne()
    ctx = AgentContext(
        investigation_id=uuid4(),
        trigger=_alert(alertname="PodRestarting", pod="checkout-7f9"),
        window_start=NOW - timedelta(minutes=5),
        window_end=NOW,
    )

    outcome = await agent.run(ctx)

    assert outcome.status.value == "degraded"
    assert any(f.kind is FindingKind.DEGRADED for f in outcome.findings)


# --- history never raises confidence in the present ---------------------------------


@pytest.mark.asyncio
async def test_a_recalled_prior_does_not_corroborate_the_present(only_mnemosyne: Any) -> None:
    """The one thing history must never do.

    A recalled prior shares the subject, so without an explicit exclusion it
    would corroborate whatever the ranker already leaned towards - and last
    Tuesday's verdict would raise confidence in this Tuesday's. Asserted on the
    verdict of a real run rather than on `rank()` directly, because the seam is
    the Finding reaching the aggregator with the exclusion applied.
    """
    from core.orchestrator.hypotheses import rank
    from tests.unit.test_hypothesis_ranking import DISK, _metric_finding, _ref

    trigger = _alert(alertname="NodeDiskFillingUp", node="node-a")
    store = InMemoryInvestigationStore()
    await store.save(_prior(trigger, days_ago=1, category=RootCauseCategory.DISK_EXHAUSTION))
    run = await investigate(trigger, store=store, bus=InMemoryEventBus())
    history = _recall_finding(run)
    assert history is not None

    node = _ref("node", "node-a")
    without = rank([_metric_finding(DISK, subject=node)])
    with_history = rank([_metric_finding(DISK, subject=node), history])

    assert with_history[0].confidence == without[0].confidence, (
        "a prior verdict raised confidence in the present one"
    )
    assert history.id not in with_history[0].supporting_finding_ids


@pytest.mark.asyncio
async def test_history_alone_proposes_nothing_not_even_unknown(only_mnemosyne: Any) -> None:
    """A run whose only substantive Finding is history is a run where nothing
    happened now. UNKNOWN would say something happened and went unexplained."""
    from core.orchestrator.hypotheses import rank

    trigger = _alert(alertname="PodRestarting", pod="checkout-7f9")
    store = InMemoryInvestigationStore()
    await store.save(_prior(trigger, days_ago=1))
    history = _recall_finding(await investigate(trigger, store=store, bus=InMemoryEventBus()))
    assert history is not None

    assert rank([history]) == []
