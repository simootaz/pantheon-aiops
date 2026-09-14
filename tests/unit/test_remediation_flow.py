"""From a verdict's recommended actions to a person being asked.

WHAT THIS FILE IS FOR
-----------------------
Three pieces sat finished and unjoined: `ApprovalGate.open_request` had no
production caller, `InvestigationState.AWAITING_APPROVAL` was declared and never
set, and `ApprovalRequestedEvent` was rendered by the AG-UI translator and
published by nothing. Each had its own passing tests. Nothing tested the join,
which is exactly how a gap between two correct halves survives.

So these assertions are about the seam. They run `investigate` and read what
came out of the gate and off the bus, rather than calling `propose` directly -
`test_proposal.py` already does that, and would keep passing if the router
stopped calling it.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from agents._base.base_agent import AgentContext, BaseAgent
from core.bus import InMemoryEventBus
from core.contracts.action import Action, BlastRadius, ExecutionState
from core.contracts.evidence import ResourceRef
from core.contracts.finding import Finding
from core.contracts.investigation import InvestigationState, Trigger, TriggerKind
from core.contracts.verdict import Verdict
from core.guardrails.approval_gate import ApprovalGate
from core.orchestrator import aggregator, dispatcher
from core.orchestrator.router import investigate
from core.store.investigations import InMemoryInvestigationStore


class _Quiet(BaseAgent):
    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return []


class _QuietLethe(BaseAgent):
    domain = "log_clustering"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return []


class _QuietMoira(BaseAgent):
    domain = "capacity"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return []


@pytest.fixture
def registered() -> Any:
    """The alert plan's agents, all quiet, restored afterwards. The findings are
    not the subject."""
    original = dict(dispatcher.AGENTS)
    dispatcher.AGENTS.clear()
    dispatcher.register("argus", _Quiet)
    dispatcher.register("lethe", _QuietLethe)
    dispatcher.register("moira", _QuietMoira)
    yield
    dispatcher.AGENTS.clear()
    dispatcher.AGENTS.update(original)


def _trigger() -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title="checkout pods restarting",
        payload={"status": "firing", "alerts": [{"labels": {"alertname": "PodRestarting"}}]},
    )


def _remediation(
    *,
    blast_radius: BlastRadius = BlastRadius.NAMESPACE,
    dry_run: bool = False,
    execution_state: ExecutionState = ExecutionState.PROPOSED,
) -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="deployment", name="checkout", namespace="shop"),
        operation="rollout_restart",
        blast_radius=blast_radius,
        dry_run=dry_run,
        execution_state=execution_state,
        reason="the verdict says the deploy is bad",
        rollback="roll back to the previous revision",
        proposed_by="zeus",
        proposed_at=datetime.now(UTC),
    )


def _recommending(*actions: Action) -> Any:
    """Patch the aggregator so its verdict recommends these.

    The aggregator recommends nothing today - `recommended_actions=[]` - and
    nothing proposes remediations, which is a separate gap. Substituting the
    verdict here tests the router's handling of one rather than waiting for a
    proposer that does not exist; the alternative is a wiring nobody exercises
    until the day it first matters.
    """
    real = aggregator.aggregate

    def _aggregate(
        investigation_id: UUID, findings: list[Finding], steps: list[Any], **kwargs: Any
    ) -> Verdict:
        verdict = real(investigation_id, findings, steps, **kwargs)
        return verdict.model_copy(update={"recommended_actions": list(actions)})

    return _aggregate


# --- the seam ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_recommended_remediation_reaches_the_approval_queue(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The link that did not exist.

    `open_request` had no production caller. An operator watching the queue saw
    nothing no matter what any run concluded.
    """
    action = _remediation()
    monkeypatch.setattr(aggregator, "aggregate", _recommending(action))
    gate = ApprovalGate()

    await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus(), gate=gate
    )

    (waiting,) = gate.pending()
    assert waiting.action_id == action.id
    assert waiting.action == action, "the queued request cannot show what it is asking about"


@pytest.mark.asyncio
async def test_the_run_says_it_is_waiting_rather_than_finished(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AWAITING_APPROVAL existed in the contract and nothing ever set it.

    A run that has asked somebody and a run that is over were the same row, and
    the second is the one an operator stops reading.
    """
    monkeypatch.setattr(aggregator, "aggregate", _recommending(_remediation()))

    investigation = await investigate(
        _trigger(),
        store=InMemoryInvestigationStore(),
        bus=InMemoryEventBus(),
        gate=ApprovalGate(),
    )

    assert investigation.state is InvestigationState.AWAITING_APPROVAL
    assert investigation.completed_at is None, (
        "a run still waiting for an approver carries a completion time, so every "
        "duration measured from it is wrong and anything sorting by it reads it as done"
    )


@pytest.mark.asyncio
async def test_the_approval_request_is_announced_on_the_bus(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`api/agui/translator.py` turns this into the A2UI approval card.

    It has been able to since the surface landed, with nothing publishing the
    event - so the card was unreachable from any run.
    """
    action = _remediation()
    monkeypatch.setattr(aggregator, "aggregate", _recommending(action))
    seen: list[Any] = []

    class _Watching(InMemoryEventBus):
        async def publish(self, event: Any, *, investigation_id: UUID | None = None) -> Any:
            seen.append(event)
            return await super().publish(event, investigation_id=investigation_id)

    await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=_Watching(), gate=ApprovalGate()
    )

    requested = [event for event in seen if event.type == "approval_requested"]
    assert len(requested) == 1
    assert requested[0].action == action


@pytest.mark.asyncio
async def test_a_waiting_run_does_not_publish_a_completion(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`InvestigationCompletedEvent` says a run reached a terminal state.

    AWAITING_APPROVAL is not one, and the translator maps that event to
    RUN_FINISHED - which closes the AG-UI stream on the very reader being asked
    to answer.
    """
    monkeypatch.setattr(aggregator, "aggregate", _recommending(_remediation()))
    seen: list[Any] = []

    class _Watching(InMemoryEventBus):
        async def publish(self, event: Any, *, investigation_id: UUID | None = None) -> Any:
            seen.append(event)
            return await super().publish(event, investigation_id=investigation_id)

    await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=_Watching(), gate=ApprovalGate()
    )

    assert not [event for event in seen if event.type == "investigation_completed"]
    assert [event for event in seen if event.type == "verdict_ready"], (
        "the verdict is still announced - a reader waiting to approve needs the "
        "conclusion the request came from"
    )


# --- the controls --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_recommending_nothing_completes_as_before(registered: Any) -> None:
    """The control, and the case every run takes today.

    Without it, a router that set AWAITING_APPROVAL unconditionally would pass
    every assertion above and no investigation would ever finish.
    """
    seen: list[Any] = []

    class _Watching(InMemoryEventBus):
        async def publish(self, event: Any, *, investigation_id: UUID | None = None) -> Any:
            seen.append(event)
            return await super().publish(event, investigation_id=investigation_id)

    investigation = await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=_Watching()
    )

    assert investigation.state is InvestigationState.COMPLETED
    assert investigation.completed_at is not None
    assert [event for event in seen if event.type == "investigation_completed"]
    assert not [event for event in seen if event.type == "approval_requested"]


@pytest.mark.asyncio
async def test_an_allowed_remediation_asks_nobody_and_the_run_completes(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run is on the policy's allow-list, so there is nothing to approve.

    The second control. A router that queued every recommended Action would put
    a prompt in front of a person for something nobody needed to decide, which
    is training for the prompts that matter.
    """
    monkeypatch.setattr(aggregator, "aggregate", _recommending(_remediation(dry_run=True)))
    gate = ApprovalGate()

    investigation = await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus(), gate=gate
    )

    assert gate.pending() == []
    assert investigation.state is InvestigationState.COMPLETED


@pytest.mark.asyncio
async def test_a_denied_remediation_asks_nobody_and_the_run_completes(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An Action that already ran is denied, and a DENY is not a slow yes.

    The run is over: there is nothing anyone can do about it, so leaving it in
    AWAITING_APPROVAL would be a row waiting for an answer nobody can give.
    """
    monkeypatch.setattr(
        aggregator,
        "aggregate",
        _recommending(_remediation(execution_state=ExecutionState.SUCCEEDED)),
    )
    gate = ApprovalGate()

    investigation = await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus(), gate=gate
    )

    assert gate.pending() == []
    assert investigation.state is InvestigationState.COMPLETED


@pytest.mark.asyncio
async def test_a_recommendation_with_no_gate_fails_loudly(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently dropping it would report the run complete.

    The worst available outcome: a remediation that needed a person, nobody
    asked, and a green row saying the investigation finished.
    """
    monkeypatch.setattr(aggregator, "aggregate", _recommending(_remediation()))

    with pytest.raises(RuntimeError, match="no approval gate was supplied"):
        await investigate(_trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus())


@pytest.mark.asyncio
async def test_several_recommendations_each_get_their_own_request(
    registered: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One request per Action, because one approval is for one act.

    A single request covering three would be an approval for content the
    approver read once and three Actions that can each change afterwards.
    """
    first, second = _remediation(), _remediation()
    monkeypatch.setattr(aggregator, "aggregate", _recommending(first, second))
    gate = ApprovalGate()

    await investigate(
        _trigger(), store=InMemoryInvestigationStore(), bus=InMemoryEventBus(), gate=gate
    )

    assert {request.action_id for request in gate.pending()} == {first.id, second.id}
