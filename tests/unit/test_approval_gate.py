"""The approval gate, and the four ways an approval could be wider than intended.

Every test below is a way a gate can exist and not gate: an approval that
outlives its timeout, one that survives the Action changing under it, one the
proposer granted themselves, and one a second click overturned.

`core/contracts/ui.py` states the rule this file implements - a response
"carries no decision authority of its own; an approval reaching the Approval
Gate is re-validated there against the request it claims to answer."

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.config import Environment
from core.contracts.action import Action, ApprovalState, BlastRadius
from core.guardrails.approval_gate import (
    ApprovalError,
    ApprovalGate,
    digest_of,
    may_execute,
)
from core.guardrails.policy import Decision, evaluate
from tests.unit.test_action_policy import an_action

START = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _Ticker:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def _gate(ticker: _Ticker | None = None, **kwargs: object) -> tuple[ApprovalGate, _Ticker]:
    clock = ticker or _Ticker()
    return ApprovalGate(clock=clock, **kwargs), clock  # type: ignore[arg-type]


def _needs_approval() -> Action:
    """An Action the policy sends to a human, so the fixture and the rule agree."""
    action = an_action(blast_radius=BlastRadius.NAMESPACE)
    assert evaluate(action, environment=Environment.STAGING).decision is Decision.REQUIRE_APPROVAL
    return action


def _ruling() -> object:
    return evaluate(_needs_approval(), environment=Environment.STAGING)


# --- a timeout fails closed --------------------------------------------------------


def test_an_unanswered_request_expires_and_never_becomes_approved() -> None:
    """A gate whose timeout defaults open is a delay, not a gate - and it is
    discovered by an action running at 04:00 because nobody was awake to say no."""
    gate, clock = _gate(ttl=timedelta(minutes=30))
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    assert gate.state(request.id) is ApprovalState.PENDING

    clock.now = START + timedelta(minutes=31)

    assert gate.state(request.id) is ApprovalState.EXPIRED
    assert not may_execute(request, action, now=clock.now)


def test_an_expired_request_cannot_then_be_answered() -> None:
    """Otherwise the timeout is advisory: answer late and it counts anyway."""
    gate, clock = _gate(ttl=timedelta(minutes=5))
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    clock.now = START + timedelta(minutes=6)

    with pytest.raises(ApprovalError, match="already expired"):
        gate.respond(request.id, action, approver="alex", approve=True)


def test_an_approval_stops_counting_once_it_expires() -> None:
    """`may_execute` re-checks the clock. An executor that read `approved` once
    and held it would carry an approval past its own timeout."""
    gate, clock = _gate(ttl=timedelta(minutes=30))
    action = _needs_approval()
    request = gate.respond(
        gate.open_request(action, evaluate(action, environment=Environment.STAGING)).id,
        action,
        approver="alex",
        approve=True,
    )

    assert may_execute(request, action, now=clock.now)
    assert not may_execute(request, action, now=START + timedelta(hours=2)), (
        "an approval outlived its expiry, so the timeout only applies to waiting"
    )


# --- an approval is for what was read, not for an id --------------------------------


def test_changing_the_action_voids_the_approval() -> None:
    """The attack this closes: propose a dry run, get it approved, flip
    `dry_run` and execute. Same id, same approval, entirely different act."""
    gate, _clock = _gate()
    # Proposed as a real change, so the policy genuinely sends it to a human.
    # (A `dry_run=True` action is ALLOWed outright and never reaches the gate,
    # which is why the flip is exercised in the other direction here.)
    proposed = _needs_approval()
    request = gate.open_request(proposed, evaluate(proposed, environment=Environment.STAGING))

    changed = proposed.model_copy(update={"operation": "delete"})

    with pytest.raises(ApprovalError, match="has changed since approval was requested"):
        gate.respond(request.id, changed, approver="alex", approve=True)


def test_an_approval_granted_before_a_change_does_not_survive_it() -> None:
    """Refusing the response is not enough. An approval already granted must
    stop applying the moment the Action it described stops matching."""
    gate, clock = _gate()
    action = _needs_approval()
    approved = gate.respond(
        gate.open_request(action, evaluate(action, environment=Environment.STAGING)).id,
        action,
        approver="alex",
        approve=True,
    )

    assert may_execute(approved, action, now=clock.now)

    widened = action.model_copy(update={"blast_radius": BlastRadius.CLUSTER})
    assert not may_execute(approved, widened, now=clock.now)


def test_an_approval_for_one_action_does_not_answer_another() -> None:
    gate, clock = _gate()
    action = _needs_approval()
    approved = gate.respond(
        gate.open_request(action, evaluate(action, environment=Environment.STAGING)).id,
        action,
        approver="alex",
        approve=True,
    )

    other = _needs_approval()
    assert other.id != action.id
    assert not may_execute(approved, other, now=clock.now)


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "delete"},
        {"parameters": {"replicas": 0}},
        {"blast_radius": BlastRadius.CLUSTER},
        {"dry_run": True},
        {"rollback": "something else"},
    ],
)
def test_every_field_an_approver_weighs_is_in_the_digest(change: dict[str, object]) -> None:
    """Exhaustive over the decision-relevant fields. One left out is a field
    that can be changed after approval without voiding it."""
    action = _needs_approval()

    assert digest_of(action.model_copy(update=change)) != digest_of(action), (
        f"changing {sorted(change)} did not change the digest, so an approval survives that change"
    )


def test_execution_progress_does_not_void_an_approval() -> None:
    """The control, and the reason the digest is not the whole model.

    `execution_state` and `receipts` change as an Action runs. Including them
    would void the approval the instant execution began - which reads as a race
    and is really a digest that included the clock.
    """
    from core.contracts.action import ExecutionState

    action = _needs_approval()
    running = action.model_copy(update={"execution_state": ExecutionState.EXECUTING})

    assert digest_of(running) == digest_of(action)


def test_parameters_in_a_different_order_are_the_same_act() -> None:
    """A digest that disagreed would void approvals for a reason no human
    could see."""
    action = _needs_approval()
    one = action.model_copy(update={"parameters": {"replicas": 4, "wait": True}})
    other = action.model_copy(update={"parameters": {"wait": True, "replicas": 4}})

    assert digest_of(one) == digest_of(other)


# --- who may answer ------------------------------------------------------------------


def test_the_proposer_cannot_approve_their_own_action() -> None:
    """Two people, or the gate is a formality that logs one person agreeing
    with themselves."""
    gate, _clock = _gate()
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    with pytest.raises(ApprovalError, match="cannot approve it"):
        gate.respond(request.id, action, approver=action.proposed_by, approve=True)


def test_someone_else_can() -> None:
    """The control. A rule refusing everyone would pass the test above."""
    gate, clock = _gate()
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    answered = gate.respond(request.id, action, approver="alex", approve=True, reason="checked")

    assert answered.approved is True
    assert answered.answered_by == "alex"
    assert may_execute(answered, action, now=clock.now)


# --- an answer stands ------------------------------------------------------------------


def test_a_rejection_cannot_be_overturned_by_answering_again() -> None:
    """Otherwise the decision belongs to whoever clicked last."""
    gate, _clock = _gate()
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))
    gate.respond(request.id, action, approver="alex", approve=False, reason="too wide")

    with pytest.raises(ApprovalError, match="already rejected"):
        gate.respond(request.id, action, approver="sam", approve=True)

    assert gate.state(request.id) is ApprovalState.REJECTED


def test_an_approval_cannot_be_re_granted_either() -> None:
    """Symmetry. A second yes would reset the clock on the first."""
    gate, _clock = _gate()
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))
    gate.respond(request.id, action, approver="alex", approve=True)

    with pytest.raises(ApprovalError, match="already approved"):
        gate.respond(request.id, action, approver="sam", approve=True)


# --- opening a request at all -----------------------------------------------------------


def test_a_denied_action_cannot_acquire_an_approval() -> None:
    """Opening a request for a DENY manufactures a way past it."""
    gate, _clock = _gate()
    action = an_action(blast_radius=BlastRadius.CLUSTER)
    denied = evaluate(action, environment=Environment.PRODUCTION)
    assert denied.decision is Decision.DENY

    with pytest.raises(ApprovalError, match="manufactures a way past it"):
        gate.open_request(action, denied)


def test_an_allowed_action_does_not_get_a_gate_it_never_needed() -> None:
    gate, _clock = _gate()
    action = an_action(blast_radius=BlastRadius.NONE)
    allowed = evaluate(action, environment=Environment.STAGING)
    assert allowed.decision is Decision.ALLOW

    with pytest.raises(ApprovalError, match="nothing"):
        gate.open_request(action, allowed)


def test_an_unknown_request_is_refused_rather_than_reported_as_pending() -> None:
    """PENDING for something never opened makes a typo indistinguishable from a
    request nobody has answered."""
    gate, _clock = _gate()

    with pytest.raises(ApprovalError, match="no approval request"):
        gate.state(uuid4())


# --- what is waiting ---------------------------------------------------------------------


def test_expired_requests_are_not_reported_as_pending() -> None:
    """A queue that grows forever teaches operators to ignore it."""
    gate, clock = _gate(ttl=timedelta(minutes=10))
    action = _needs_approval()
    gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    assert len(gate.pending()) == 1

    clock.now = START + timedelta(minutes=11)
    assert gate.pending() == []


def test_a_request_renders_without_leaking_anything() -> None:
    """It goes to an API and an audit trail."""
    gate, _clock = _gate()
    action = _needs_approval()
    request = gate.open_request(action, evaluate(action, environment=Environment.STAGING))

    rendered = request.as_dict()

    assert rendered["action_id"] == str(action.id)
    assert rendered["rule"] == "default-requires-a-human"
    assert "action_digest" not in rendered, (
        "the digest is an internal check, not something an approver acts on"
    )
