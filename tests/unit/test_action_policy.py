"""What the policy allows, and - more importantly - what it refuses to allow by
default.

The ordering is the whole design: the last rule is REQUIRE_APPROVAL, so anything
nobody classified gets a human rather than permission. The tests that matter are
the ones which would catch that ordering being inverted, or a new blast radius
quietly landing on the allowed side.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.config import Environment
from core.contracts.action import Action, ActionReceipt, BlastRadius, ExecutionState
from core.contracts.evidence import ResourceRef
from core.guardrails.approval_gate import ApprovalGate
from core.guardrails.executor import NotPermitted, execute
from core.guardrails.policy import (
    HARMLESS,
    IRREVERSIBLE_IN_PRODUCTION,
    SPENT,
    Decision,
    evaluate,
)

#: Radii a rollback is mandatory for - the contract refuses to build one without.
NEEDS_ROLLBACK = {BlastRadius.NAMESPACE, BlastRadius.CLUSTER, BlastRadius.MULTI_CLUSTER}

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


async def _ok(operation: str, parameters: dict[str, object]) -> str:
    return f"{operation} accepted"


def an_action(
    *,
    blast_radius: BlastRadius = BlastRadius.SINGLE_WORKLOAD,
    dry_run: bool = False,
    execution_state: ExecutionState = ExecutionState.PROPOSED,
) -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="deployment", name="checkout"),
        operation="rollout_restart",
        blast_radius=blast_radius,
        dry_run=dry_run,
        execution_state=execution_state,
        reason="the verdict says the deploy is bad",
        rollback="roll back to the previous revision" if blast_radius in NEEDS_ROLLBACK else None,
        proposed_by="zeus",
        proposed_at=datetime.now(tz=UTC),
    )


# --- the default, which is the design ---------------------------------------------


@pytest.mark.parametrize("radius", sorted(BlastRadius, key=str))
def test_no_blast_radius_is_allowed_by_default(radius: BlastRadius) -> None:
    """Exhaustive over the enum ON PURPOSE.

    A new `BlastRadius` member added later must not land on the allowed side by
    default. Parametrising over the enum means adding one without deciding where
    it belongs fails here rather than shipping as permission.
    """
    ruling = evaluate(an_action(blast_radius=radius), environment=Environment.STAGING)

    if radius in HARMLESS:
        assert ruling.allowed, f"{radius.value} is in HARMLESS but was not allowed"
    else:
        assert not ruling.allowed, (
            f"{radius.value} was ALLOWED without a human. If that is deliberate, add "
            "it to HARMLESS with a reason; the default must not decide it silently."
        )


def test_an_unclassified_change_asks_for_a_human_rather_than_refusing() -> None:
    """REQUIRE_APPROVAL, not DENY. A default of DENY would be safe and useless -
    every new operation would be dead until someone edited this file."""
    ruling = evaluate(an_action(blast_radius=BlastRadius.NAMESPACE))

    assert ruling.decision is Decision.REQUIRE_APPROVAL
    assert ruling.rule == "default-requires-a-human"


def test_allowed_is_true_only_for_allow() -> None:
    """`!= DENY` is the natural thing to write and it treats REQUIRE_APPROVAL as
    permission. This is why the property exists rather than callers comparing."""
    needs_human = evaluate(an_action(blast_radius=BlastRadius.NAMESPACE))

    assert needs_human.decision is Decision.REQUIRE_APPROVAL
    assert needs_human.allowed is False, (
        "REQUIRE_APPROVAL was reported as allowed, so a caller writing "
        "`if ruling.allowed` would execute an unapproved action"
    )


# --- the denials --------------------------------------------------------------------


@pytest.mark.parametrize("state", sorted(SPENT, key=str))
def test_an_action_that_already_ran_is_refused(state: ExecutionState) -> None:
    """Allowing it would let a retry re-run a remediation that already succeeded."""
    ruling = evaluate(an_action(execution_state=state, dry_run=False))

    assert ruling.decision is Decision.DENY
    assert ruling.rule == "already-executed"


def test_a_spent_action_is_refused_even_as_a_dry_run() -> None:
    """Ordering: the execution-state rule comes FIRST.

    If the dry-run rule ran first, an in-flight Action re-marked `dry_run` would
    come back ALLOW - and `dry_run` is a field a caller sets.

    EXECUTING rather than SUCCEEDED, because the contract already refuses to
    build a SUCCEEDED action that claims to be a dry run. It does not refuse the
    other three spent states, so for those the ordering here is the only thing
    standing in the way - which is what makes this testable rather than a claim
    about an object nobody can construct.
    """
    ruling = evaluate(an_action(execution_state=ExecutionState.EXECUTING, dry_run=True))

    assert ruling.decision is Decision.DENY
    assert ruling.rule == "already-executed"


def test_the_contract_separately_refuses_a_succeeded_dry_run() -> None:
    """The one spent state the policy never sees, because it cannot be built.

    Asserted so the division of labour is visible: widening the contract to the
    other three would make the ordering test above unconstructable, and an
    ordering nothing can exercise is the unfailable-guard shape.
    """
    with pytest.raises(ValidationError, match="SUCCEEDED while dry_run is true"):
        an_action(execution_state=ExecutionState.SUCCEEDED, dry_run=True)


@pytest.mark.parametrize("radius", sorted(IRREVERSIBLE_IN_PRODUCTION, key=str))
def test_a_cluster_wide_change_in_production_is_denied_not_escalated(
    radius: BlastRadius,
) -> None:
    """A deny rather than an approval nobody could grant.

    Break-glass lives in `core/cerberus/policy/revocation.py`, which is a stub.
    Returning REQUIRE_APPROVAL here would send an operator to a gate that cannot
    let them through, and the failure would present as a stuck approval.
    """
    ruling = evaluate(an_action(blast_radius=radius), environment=Environment.PRODUCTION)

    assert ruling.decision is Decision.DENY
    assert ruling.rule == "too-wide-for-production"


def test_the_same_change_outside_production_only_needs_approval() -> None:
    """The control. A rule that denied everywhere would pass the test above and
    make staging unusable."""
    ruling = evaluate(an_action(blast_radius=BlastRadius.CLUSTER), environment=Environment.STAGING)

    assert ruling.decision is Decision.REQUIRE_APPROVAL


def test_production_denial_beats_the_dry_run_allowance() -> None:
    """Ordering again. `dry_run` is caller-supplied, and a connector that ignores
    it would turn a claimed rehearsal into a cluster-wide change."""
    ruling = evaluate(
        an_action(blast_radius=BlastRadius.CLUSTER, dry_run=True),
        environment=Environment.PRODUCTION,
    )

    assert ruling.decision is Decision.DENY


# --- the allowances, and what they rest on ------------------------------------------


def test_a_dry_run_is_allowed_and_says_what_it_is_assuming() -> None:
    """The assumption is load-bearing and belongs in the ruling, not in a comment
    nobody reads at the point of decision."""
    ruling = evaluate(an_action(blast_radius=BlastRadius.NAMESPACE, dry_run=True))

    assert ruling.allowed
    assert ruling.rule == "dry-run"
    assert "connector actually implements one" in ruling.because


def test_an_action_with_no_blast_radius_needs_no_approver() -> None:
    ruling = evaluate(an_action(blast_radius=BlastRadius.NONE))

    assert ruling.allowed
    assert ruling.rule == "no-blast-radius"


# --- a ruling has to be readable ------------------------------------------------------


@pytest.mark.parametrize(
    ("radius", "environment"),
    [
        (BlastRadius.NONE, Environment.LOCAL),
        (BlastRadius.SINGLE_WORKLOAD, Environment.STAGING),
        (BlastRadius.CLUSTER, Environment.PRODUCTION),
    ],
)
def test_every_ruling_names_its_rule_and_explains_itself(
    radius: BlastRadius, environment: Environment
) -> None:
    """ "Denied" with no rule named is unauditable. At three in the morning the
    question is which no, not whether."""
    ruling = evaluate(an_action(blast_radius=radius), environment=environment)

    assert ruling.rule, "a ruling with no rule name"
    assert len(ruling.because.split()) >= 8, f"too terse to act on: {ruling.because!r}"
    assert ruling.as_dict()["decision"] == ruling.decision.value


def test_the_environment_can_be_asked_about_without_being_it() -> None:
    """Injectable, so a test can ask what production would say. Without this the
    production rules could only be exercised in production."""
    action = an_action(blast_radius=BlastRadius.CLUSTER)

    assert evaluate(action, environment=Environment.PRODUCTION).decision is Decision.DENY
    assert evaluate(action, environment=Environment.LOCAL).decision is Decision.REQUIRE_APPROVAL


def test_the_allowed_set_is_small_and_stays_small() -> None:
    """A tripwire, not a principle.

    Growing the allow-list is how a human-in-the-loop system stops having one.
    Crossing this should force someone to ask whether the new entry really
    changes nothing, rather than noticing a year later.
    """
    assert len(HARMLESS) <= 2, (
        f"{len(HARMLESS)} blast radii are allowed without an approver: "
        f"{sorted(r.value for r in HARMLESS)}"
    )


# --- a receipt names the rule that decided it ------------------------------------------------


@pytest.mark.asyncio
async def test_a_receipt_names_the_rule_that_permitted_it() -> None:
    """A receipt said what happened and never why it was allowed to.

    For a refusal the rule lived in an exception message; for a success it was
    nowhere at all. "Why did this run" is the first question asked afterwards,
    and the record could not answer it.
    """
    action = an_action(blast_radius=BlastRadius.SINGLE_WORKLOAD, dry_run=True)

    receipt = await execute(action, perform=_ok, connector="alertmanager")

    assert receipt.decided_by, "the receipt cannot say what let this run"
    assert receipt.decided_by == evaluate(action, environment=Environment.STAGING).rule


@pytest.mark.asyncio
async def test_a_refusal_carries_the_rule_too() -> None:
    """The refusal path is where it mattered least and was already worst: the
    rule existed only in a string nobody stores."""
    action = an_action(blast_radius=BlastRadius.CLUSTER, dry_run=False)

    with pytest.raises(NotPermitted) as refused:
        await execute(
            action, perform=_ok, connector="alertmanager", environment=Environment.PRODUCTION
        )

    assert refused.value.receipt.decided_by
    assert refused.value.receipt.state is ExecutionState.SKIPPED


def test_a_receipt_cannot_be_constructed_without_a_rule() -> None:
    """Required rather than defaulted. A default would be filled in by the one
    call site that forgot, which is the site that most needed to say."""
    # The ignore is the second half of the guard: mypy refuses the omission at
    # the type level and pydantic refuses it at runtime, and only the second is
    # reachable from code that was never type-checked - a JSON body, a
    # deserialised record, a Go or TypeScript caller of the generated contract.
    with pytest.raises(ValidationError):
        ActionReceipt(at=NOW, state=ExecutionState.SUCCEEDED, connector="alertmanager")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        ActionReceipt(
            at=NOW,
            state=ExecutionState.SUCCEEDED,
            connector="alertmanager",
            decided_by="",
        )


@pytest.mark.asyncio
async def test_an_approval_id_is_recorded_only_when_a_rule_asked_for_one() -> None:
    """Recording one on a receipt for a rule that required no approval would
    make the trail say a person signed off on something nobody was asked
    about.

    An approval IS supplied here, for a different Action that genuinely needed
    one. Passing `None` could not express the claim - the plant that dropped
    the decision check passed it, because there was no approval to record
    either way.
    """
    needs_one = an_action(blast_radius=BlastRadius.NAMESPACE, dry_run=False)
    gate = ApprovalGate()
    elsewhere = gate.open_request(needs_one, evaluate(needs_one, environment=Environment.STAGING))

    allowed = an_action(blast_radius=BlastRadius.SINGLE_WORKLOAD, dry_run=True)
    receipt = await execute(allowed, perform=_ok, connector="alertmanager", approval=elsewhere)

    assert receipt.decided_by == "dry-run"
    assert receipt.approval_id is None, (
        "an approval for another Action was recorded against one nobody was asked about"
    )
