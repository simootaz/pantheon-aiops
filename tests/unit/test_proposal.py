"""The request half of the gate: who gets asked, and who does not.

The interesting assertions are the two negatives. An ALLOW must not open a
request - a gate invented where none was asked for trains people to click
through the ones that matter. A DENY must not open one either: an audit trail
containing an approval for an Action policy denied tells a confusing story even
though `executor.execute` re-evaluates and refuses it anyway.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.config import Environment
from core.contracts.action import Action, ApprovalState, BlastRadius, ExecutionState
from core.guardrails.approval_gate import ApprovalGate
from core.guardrails.policy import Decision, evaluate
from core.guardrails.proposal import propose, propose_all
from tests.unit.test_action_policy import an_action

START = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class _Ticker:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def _gate() -> tuple[ApprovalGate, _Ticker]:
    clock = _Ticker()
    return ApprovalGate(clock=clock), clock


def _needs_a_person() -> Action:
    action = an_action(blast_radius=BlastRadius.NAMESPACE)
    assert evaluate(action, environment=Environment.STAGING).decision is Decision.REQUIRE_APPROVAL
    return action


def _allowed() -> Action:
    """A dry run. The policy's allow-list is deliberately tiny."""
    action = an_action(blast_radius=BlastRadius.NAMESPACE, dry_run=True)
    assert evaluate(action, environment=Environment.STAGING).decision is Decision.ALLOW
    return action


def _denied() -> Action:
    action = an_action(execution_state=ExecutionState.SUCCEEDED)
    assert evaluate(action, environment=Environment.STAGING).decision is Decision.DENY
    return action


# --- the link that was missing ------------------------------------------------------


def test_an_action_needing_a_person_puts_one_in_the_queue() -> None:
    """The whole point. Before this, `open_request` had no production caller.

    `executor.execute` refused with "needs approval and none was supplied" and
    nothing turned that refusal into somebody being asked, so the queue was
    unreachable by any path through the platform.
    """
    gate, _clock = _gate()
    action = _needs_a_person()

    proposal = propose(action, gate=gate, environment=Environment.STAGING)

    assert proposal.waiting
    assert proposal.approval is not None
    assert gate.pending() == [proposal.approval], "the request is not in the queue a person reads"


def test_the_queued_request_carries_the_action_that_was_proposed() -> None:
    """Not a copy, and not an id. The approver reads this object."""
    gate, _clock = _gate()
    action = _needs_a_person()

    propose(action, gate=gate, environment=Environment.STAGING)

    (waiting,) = gate.pending()
    assert waiting.action == action


def test_the_request_records_the_rule_that_required_it() -> None:
    """ "Someone must approve" with no rule named is unauditable.

    The ruling is passed through rather than re-evaluated inside the gate:
    evaluating twice can produce two answers, and the request would then cite a
    rule that did not run.
    """
    gate, _clock = _gate()
    action = _needs_a_person()

    proposal = propose(action, gate=gate, environment=Environment.STAGING)

    assert proposal.approval is not None
    assert proposal.approval.ruling.rule == proposal.ruling.rule


# --- the two negatives --------------------------------------------------------------


def test_an_allowed_action_gets_no_gate_it_never_needed() -> None:
    """A gate invented where none was asked for is worse than no gate.

    Every prompt a person clears without a decision to make is training for the
    one that mattered.
    """
    gate, _clock = _gate()

    proposal = propose(_allowed(), gate=gate, environment=Environment.STAGING)

    assert proposal.ready
    assert proposal.approval is None
    assert gate.pending() == []


def test_a_denied_action_is_not_offered_to_an_approver() -> None:
    """A DENY is not a slow yes.

    `executor.execute` re-evaluates and refuses regardless, so nothing would
    actually run - but an audit trail holding an approval for an Action policy
    denied says a person authorised something the system had already refused,
    and that is the record somebody reads afterwards.
    """
    gate, _clock = _gate()

    proposal = propose(_denied(), gate=gate, environment=Environment.STAGING)

    assert proposal.refused
    assert proposal.approval is None
    assert gate.pending() == []


def test_ready_is_not_the_absence_of_an_approval() -> None:
    """The trap this property exists to close.

    `approval is None` is true for an ALLOW and for a DENY. A caller reading it
    as clearance would execute exactly the Actions policy refused.
    """
    gate, _clock = _gate()

    denied = propose(_denied(), gate=gate, environment=Environment.STAGING)

    assert denied.approval is None
    assert not denied.ready, "a denied Action reported itself ready to run"


def test_a_waiting_proposal_is_not_ready_either() -> None:
    """Asked is not answered, and neither is permission."""
    gate, _clock = _gate()

    proposal = propose(_needs_a_person(), gate=gate, environment=Environment.STAGING)

    assert proposal.waiting
    assert not proposal.ready


# --- several at once ----------------------------------------------------------------


def test_one_refusal_does_not_silence_the_rest() -> None:
    """A verdict recommending three remediations, one denied, must still ask.

    Stopping at the first refusal would put nothing in front of a person and
    give them no way to learn that two of the three were answerable.
    """
    gate, _clock = _gate()

    proposals = propose_all(
        [_denied(), _needs_a_person(), _allowed()],
        gate=gate,
        environment=Environment.STAGING,
    )

    assert [p.ruling.decision for p in proposals] == [
        Decision.DENY,
        Decision.REQUIRE_APPROVAL,
        Decision.ALLOW,
    ]
    assert len(gate.pending()) == 1, "exactly one of the three needed a person"


def test_proposing_nothing_asks_nobody() -> None:
    """A verdict with no recommended actions is the ordinary case today."""
    gate, _clock = _gate()

    assert propose_all([], gate=gate, environment=Environment.STAGING) == []
    assert gate.pending() == []


# --- what the caller can do with the answer -----------------------------------------


def test_the_opened_request_can_be_answered_and_then_spent() -> None:
    """End to end: propose, answer, and the approval covers the Action.

    This is the assertion that the two halves fit together. Each half passed its
    own tests while nothing joined them, which is exactly how the gap survived.
    """
    from core.guardrails.approval_gate import may_execute

    gate, clock = _gate()
    action = _needs_a_person()

    proposal = propose(action, gate=gate, environment=Environment.STAGING)
    assert proposal.approval is not None

    answered = gate.respond(proposal.approval.id, action, approver="someone-else", approve=True)

    assert answered.state(now=clock.now) is ApprovalState.APPROVED
    assert may_execute(answered, action, now=clock.now)


def test_an_approval_opened_here_still_expires() -> None:
    """Nothing about this path makes a request outlive its timeout.

    Worth asserting rather than assuming: the gate's TTL is applied in
    `open_request`, and a proposal path that constructed its own request would
    be the obvious place for it to go missing.
    """
    gate, clock = _gate()
    action = _needs_a_person()

    proposal = propose(action, gate=gate, environment=Environment.STAGING)
    assert proposal.approval is not None

    clock.now = START + timedelta(hours=2)

    assert proposal.approval.state(now=clock.now) is ApprovalState.EXPIRED
    assert gate.pending() == []


def test_the_environment_is_honoured_rather_than_read_from_configuration() -> None:
    """A test can ask what production would say without being production.

    And the reverse matters more: a proposal path that ignored the argument
    would evaluate every Action against the running environment, so a staging
    test of a production rule would quietly pass.
    """
    gate, _clock = _gate()
    wide = an_action(blast_radius=BlastRadius.CLUSTER)

    in_production = propose(wide, gate=gate, environment=Environment.PRODUCTION)
    in_staging = propose(wide, gate=gate, environment=Environment.STAGING)

    assert in_production.ruling.decision is Decision.DENY, (
        "a cluster-wide change in production is a hard deny - see policy.IRREVERSIBLE_IN_PRODUCTION"
    )
    assert in_staging.ruling.decision is Decision.REQUIRE_APPROVAL
    assert len(gate.pending()) == 1, "only the staging proposal should have asked anybody"


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_the_ruling_is_returned_whatever_it_says(environment: Environment) -> None:
    """`propose` returns in all three cases rather than raising on refusal.

    A caller proposing several Actions gets several answers. Raising on the
    first DENY would make `propose_all` stop at it.
    """
    gate, _clock = _gate()

    proposal = propose(_denied(), gate=gate, environment=environment)

    assert proposal.ruling.rule, "the ruling came back without naming its rule"
