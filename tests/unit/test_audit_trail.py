"""The audit trail: append-only in fact, and what the write path records in it.

`Investigation.audit` has existed since Phase 1 with no writer, so an
investigation that silenced an alert recorded the receipt and nothing about the
decision behind it. These are the entries that close that gap, and the checks
that make "append-only" a property rather than a docstring.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.cerberus.audit.attach import attach, record_action, record_approval_sought
from core.cerberus.audit.log import AuditLog
from core.contracts.action import Action, ActionReceipt, BlastRadius, ExecutionState
from core.contracts.credentials import AuditEvent
from core.contracts.evidence import ResourceRef
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def _action(blast_radius: BlastRadius = BlastRadius.SINGLE_WORKLOAD) -> Action:
    return Action(
        id=uuid4(),
        target=ResourceRef(kind="alert", name="CheckoutErrorRateHigh"),
        operation="create_silence",
        blast_radius=blast_radius,
        reason="a known symptom",
        rollback="expire the silence",
        proposed_by="zeus",
        proposed_at=NOW,
    )


def _receipt(state: ExecutionState, detail: str = "done") -> ActionReceipt:
    # `decided_by` is required and cannot be empty: a receipt that says what
    # happened and not what let it cannot answer the first question asked
    # afterwards. The executor sets it from the ruling that ran.
    return ActionReceipt(
        at=NOW,
        state=state,
        connector="alertmanager",
        detail=detail,
        decided_by="silence-in-staging",
    )


def _investigation() -> Investigation:
    return Investigation(
        id=uuid4(),
        state=InvestigationState.RUNNING,
        trigger=Trigger(kind=TriggerKind.ALERT, received_at=NOW, source="alertmanager", title="t"),
        created_at=NOW,
    )


# --- append-only is a property, not a docstring -------------------------------------


def test_the_log_cannot_be_emptied_through_what_it_hands_back() -> None:
    """`log.entries().clear()` reads as clearing a local variable, and on the
    internal list it would empty an append-only trail."""
    log = AuditLog()
    log.append(AuditEvent.GRANTED, actor="zeus", detail="something")

    log.entries().clear()

    assert len(log) == 1


def test_an_entry_cannot_be_edited_after_it_is_appended() -> None:
    """A trail that can be rewritten answers nothing."""
    log = AuditLog()
    entry = log.append(AuditEvent.GRANTED, actor="zeus", detail="something")

    with pytest.raises(ValueError, match=r"frozen|immutable"):
        entry.detail = "something else"


def test_there_is_no_way_to_remove_an_entry() -> None:
    """Asserted on the surface, because a `delete` added later would be the one
    change that makes every other guarantee here meaningless."""
    names = ("delete", "remove", "update", "clear")
    forbidden = [name for name in names if hasattr(AuditLog, name)]

    assert not forbidden, f"AuditLog exposes {forbidden}; the log is append-only"


# --- a credential must not reach the trail ------------------------------------------


def test_a_configured_secret_in_the_detail_is_redacted_on_the_way_in() -> None:
    """On the way IN, not on the way out. A value that reached storage is a
    value in a memory dump, whatever a reader is later shown.

    A CONFIGURED secret, matched literally. My first version of this test used
    an unregistered key inside a JSON blob and asserted the pattern rules would
    catch it - they do not, because a string has no keys for a key-shaped rule
    to match. The literals are what close that, exactly as in the log filter.
    """
    log = AuditLog(secrets=["gsk_live_must_not_persist"])

    entry = log.append(
        AuditEvent.GRANTED,
        actor="zeus",
        detail='connected with {"api_key": "gsk_live_must_not_persist"}',
    )

    assert "gsk_live_must_not_persist" not in entry.detail
    assert "gsk_live_must_not_persist" not in str(log.entries()[0])


def test_the_readable_part_survives_redaction() -> None:
    """The control. A redactor that blanked everything would pass the test above
    and destroy the trail it exists to protect."""
    log = AuditLog(secrets=[])

    entry = log.append(AuditEvent.DENIED, actor="zeus", detail="create_silence -> skipped")

    assert "create_silence" in entry.detail


# --- what the write path records ------------------------------------------------------


def test_an_executed_action_is_recorded_as_granted() -> None:
    log = AuditLog()
    action = _action()

    entry = record_action(log, action, _receipt(ExecutionState.SUCCEEDED))

    assert entry.event is AuditEvent.GRANTED
    assert "create_silence" in entry.detail
    assert "single_workload" in entry.detail


def test_a_refused_action_is_recorded_as_denied() -> None:
    """The entry that matters most afterwards. "Nobody proposed this" and
    "somebody proposed it and policy said no" are different facts, and only the
    trail can tell them apart."""
    log = AuditLog()

    entry = record_action(
        log, _action(), _receipt(ExecutionState.SKIPPED, "denied by policy (too-wide)")
    )

    assert entry.event is AuditEvent.DENIED
    assert "too-wide" in entry.detail


def test_an_action_that_ran_and_failed_is_not_recorded_as_refused() -> None:
    """FAILED means it ran. Recording it as DENIED would say the system stopped
    something it actually attempted."""
    log = AuditLog()

    entry = record_action(log, _action(), _receipt(ExecutionState.FAILED, "500 from upstream"))

    assert entry.event is AuditEvent.GRANTED, (
        "a failed execution was recorded as a refusal, so the trail says the "
        "action never ran when it did"
    )


def test_a_dry_run_is_recorded_as_having_run() -> None:
    log = AuditLog()

    entry = record_action(log, _action(), _receipt(ExecutionState.DRY_RUN))

    assert entry.event is AuditEvent.GRANTED
    assert "dry_run" in entry.detail


def test_asking_for_an_approval_is_recorded_before_the_answer() -> None:
    """An approval that expires unanswered leaves no other trace, and "nobody
    was asked" versus "somebody was asked and did not reply" is the distinction
    an operator most needs at three in the morning."""
    log = AuditLog()

    entry = record_approval_sought(log, _action(BlastRadius.NAMESPACE))

    assert entry.event is AuditEvent.APPROVAL_REQUESTED
    assert "waiting for an approver" in entry.detail


# --- attaching to the Investigation ----------------------------------------------------


def test_an_investigation_carries_only_its_own_entries() -> None:
    """A shared log would otherwise put one investigation's decisions on
    another's record."""
    log = AuditLog()
    mine, theirs = _investigation(), _investigation()
    record_action(log, _action(), _receipt(ExecutionState.SUCCEEDED), investigation_id=mine.id)
    record_action(log, _action(), _receipt(ExecutionState.SUCCEEDED), investigation_id=theirs.id)

    attached = attach(mine, log)

    assert len(attached.audit) == 1
    assert attached.audit[0].investigation_id == mine.id


def test_attaching_returns_a_copy_rather_than_mutating() -> None:
    """The store saves whole documents; mutating in place would leave the saved
    copy and the in-memory one disagreeing about a trail that exists to be
    trusted."""
    log = AuditLog()
    investigation = _investigation()
    record_action(
        log, _action(), _receipt(ExecutionState.SUCCEEDED), investigation_id=investigation.id
    )

    attached = attach(investigation, log)

    assert investigation.audit == [], "the original was mutated"
    assert len(attached.audit) == 1


def test_attaching_twice_does_not_lose_what_was_already_there() -> None:
    """Entries recorded earlier in a run must survive a second attach."""
    log = AuditLog()
    investigation = _investigation()
    record_approval_sought(log, _action(), investigation_id=investigation.id)

    once = attach(investigation, log)
    record_action(
        log, _action(), _receipt(ExecutionState.SUCCEEDED), investigation_id=investigation.id
    )
    twice = attach(once, log)

    assert len(twice.audit) >= 2
    assert {entry.event for entry in twice.audit} >= {
        AuditEvent.APPROVAL_REQUESTED,
        AuditEvent.GRANTED,
    }


def test_entries_can_be_filtered_by_event() -> None:
    """ "Show me every refusal" is the first question asked of a trail."""
    log = AuditLog()
    record_action(log, _action(), _receipt(ExecutionState.SUCCEEDED))
    record_action(log, _action(), _receipt(ExecutionState.SKIPPED, "denied"))

    assert len(log.entries(event=AuditEvent.DENIED)) == 1
    assert len(log.entries(event=AuditEvent.GRANTED)) == 1


def test_entries_recorded_elsewhere_can_be_adopted_in_order() -> None:
    """For a run whose audit is assembled after the fact. Still append-only:
    nothing here replaces an entry already in."""
    source = AuditLog()
    first = source.append(AuditEvent.GRANTED, actor="zeus", detail="one")
    second = source.append(AuditEvent.DENIED, actor="zeus", detail="two")

    target = AuditLog()
    target.extend_from([first, second])

    assert [entry.detail for entry in target.entries()] == ["one", "two"]
