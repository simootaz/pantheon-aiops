"""Delivery guarantees, and a cursor that can tell it missed something.

The bus is in memory: nothing is persisted, nothing is acknowledged, and a
process that dies takes every event with it. That is AT_MOST_ONCE, and saying
so is the point - the only thing worse than a bus that loses events is one that
loses them while something downstream believes it does not.

What makes that workable is that the loss is detectable at the reader. Sequence
numbers are monotonic within an investigation, so a consumer that sees 5 after 3
knows it missed 4.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from core.bus import InMemoryEventBus
from core.contracts.events import (
    DeliveryGuarantee,
    EventEnvelope,
    ReplayCursor,
    TriggerReceivedEvent,
)
from core.contracts.investigation import Trigger, TriggerKind

RUN = uuid4()
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _event() -> TriggerReceivedEvent:
    return TriggerReceivedEvent(
        investigation_id=RUN,
        trigger=Trigger(kind=TriggerKind.ALERT, source="test", title="synthetic", received_at=NOW),
    )


def _envelope(sequence: int) -> EventEnvelope:
    return EventEnvelope(id=uuid4(), emitted_at=NOW, event=_event(), sequence=sequence)


# --- the guarantee is declared, not assumed ---------------------------------------------


def test_the_in_memory_bus_admits_it_can_lose_events() -> None:
    """Declaring anything stronger would let a consumer believe a picture was
    complete when the bus cannot say so."""
    assert InMemoryEventBus().guarantee is DeliveryGuarantee.AT_MOST_ONCE


def test_a_consumer_can_compare_what_it_needs_against_what_it_gets() -> None:
    """The reason the enum exists rather than a docstring. A consumer requiring
    more than a bus offers must be able to say so at wiring time instead of
    discovering it as a gap during an incident."""
    bus = InMemoryEventBus()

    assert bus.guarantee is not DeliveryGuarantee.AT_LEAST_ONCE
    assert bus.guarantee is not DeliveryGuarantee.EXACTLY_ONCE


# --- a fresh cursor has seen nothing, which is not the same as seeing zero -----------------


def test_a_fresh_cursor_has_seen_nothing() -> None:
    """`None` rather than -1 or 0. The bus numbers from 0, so "seen nothing" and
    "seen the first event" are different facts - and a sentinel conflating them
    would drop the first event of every run."""
    cursor = ReplayCursor(investigation_id=RUN)

    assert cursor.sequence is None
    assert cursor.accepts(_envelope(0)), "the first event of the run was refused"


def test_the_first_event_leaves_no_gap() -> None:
    """A cursor that counted the distance from a sentinel would report the
    first event of every run as a gap of one."""
    cursor = ReplayCursor(investigation_id=RUN).advanced(_envelope(0))

    assert cursor.sequence == 0
    assert cursor.gaps == 0
    assert cursor.complete


def test_a_run_that_starts_at_a_later_sequence_is_not_a_gap() -> None:
    """A consumer attaching mid-run has not lost anything; it was not there.
    Counting the events before it started would make every late subscriber
    report an incomplete picture of a run that was fine."""
    cursor = ReplayCursor(investigation_id=RUN).advanced(_envelope(40))

    assert cursor.gaps == 0


# --- a gap is a fact, not a skip ------------------------------------------------------------


def test_a_missing_event_is_counted() -> None:
    """What makes AT_MOST_ONCE workable: the loss is detectable at the reader
    rather than invisible."""
    cursor = ReplayCursor(investigation_id=RUN)
    cursor = cursor.advanced(_envelope(0))
    cursor = cursor.advanced(_envelope(2))

    assert cursor.sequence == 2
    assert cursor.gaps == 1
    assert not cursor.complete


def test_the_size_of_the_gap_is_carried_not_just_its_existence() -> None:
    """Missing one event and missing forty are different situations and only
    the count says which."""
    cursor = ReplayCursor(investigation_id=RUN).advanced(_envelope(0))

    assert cursor.advanced(_envelope(41)).gaps == 40


def test_gaps_accumulate_across_a_run() -> None:
    """A cursor that reported only the last gap would say a run missing three
    separate events had missed one."""
    cursor = ReplayCursor(investigation_id=RUN)
    for sequence in (0, 2, 5):
        cursor = cursor.advanced(_envelope(sequence))

    assert cursor.gaps == 3


# --- what a cursor refuses ---------------------------------------------------------------------


def test_the_same_event_twice_is_not_read_twice() -> None:
    """A repeat is what a retry looks like on this bus, and a consumer that
    reprocessed one would double-count."""
    cursor = ReplayCursor(investigation_id=RUN).advanced(_envelope(3))

    again = cursor.advanced(_envelope(3))

    assert again.sequence == 3
    assert again.gaps == 0
    assert not cursor.accepts(_envelope(3))


def test_a_late_event_does_not_rewind_the_cursor() -> None:
    """Moving it back would replay everything after it, which turns one late
    event into a storm of duplicates."""
    cursor = ReplayCursor(investigation_id=RUN).advanced(_envelope(9))

    rewound = cursor.advanced(_envelope(4))

    assert rewound.sequence == 9
    assert rewound.gaps == 0


def test_advancing_returns_a_new_cursor_rather_than_mutating() -> None:
    """A consumer holding one across a retry must not have it moved under it by
    a read that then failed."""
    cursor = ReplayCursor(investigation_id=RUN)

    moved = cursor.advanced(_envelope(7))

    assert cursor.sequence is None
    assert moved.sequence == 7


# --- against the real bus ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cursor_reads_a_whole_run_off_the_bus_without_gaps() -> None:
    """The control. A cursor that reported gaps on a complete stream would make
    the count meaningless, and every consumer would learn to ignore it."""
    bus = InMemoryEventBus()
    for _ in range(5):
        await bus.publish(_event(), investigation_id=RUN)

    cursor = ReplayCursor(investigation_id=RUN)
    for envelope in bus.published:
        cursor = cursor.advanced(envelope)

    assert cursor.sequence == 4
    assert cursor.complete


@pytest.mark.asyncio
async def test_a_consumer_that_missed_a_delivery_can_say_so() -> None:
    """Which is the whole point. A partial picture reported as partial is
    something an operator can act on; a partial picture reported as complete is
    not."""
    bus = InMemoryEventBus()
    for _ in range(5):
        await bus.publish(_event(), investigation_id=RUN)

    delivered = [envelope for envelope in bus.published if envelope.sequence != 2]
    cursor = ReplayCursor(investigation_id=RUN)
    for envelope in delivered:
        cursor = cursor.advanced(envelope)

    assert cursor.gaps == 1
    assert not cursor.complete


@pytest.mark.asyncio
async def test_sequences_are_per_investigation() -> None:
    """A cursor is scoped to one run, so a shared counter would make every
    second run look like it started mid-stream."""
    bus = InMemoryEventBus()
    other: UUID = uuid4()

    await bus.publish(_event(), investigation_id=RUN)
    await bus.publish(_event(), investigation_id=other)

    assert [envelope.sequence for envelope in bus.published] == [0, 0]
