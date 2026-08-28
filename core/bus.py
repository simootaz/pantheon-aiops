"""The internal event bus.

Everything that happens during a run is published here as an `EventEnvelope`.
`api/agui/translator.py` reads from it and maps onto AG-UI at the edge; nothing
upstream of that edge knows AG-UI exists (ADR 0006).

The in-memory implementation is deliberate and temporary. Phase 2 replaces it
with something durable once `core/memory/` and the worker exist - at which point
the Protocol below is the seam that makes the swap a one-line change rather than
a refactor.

Sequence numbers are assigned here rather than by publishers. Replay depends on
order, and an ordering that each caller is trusted to get right is an ordering
that will eventually be wrong.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from core.contracts.events import Event, EventEnvelope


class EventBus(Protocol):
    """What the rest of Pantheon depends on. Implementations vary; this does not."""

    async def publish(self, event: Event, *, investigation_id: UUID | None = None) -> EventEnvelope:
        """Wrap `event` in an envelope, assign its sequence, and deliver it."""
        ...


class InMemoryEventBus:
    """An event bus that remembers everything, for development and tests.

    Not durable and not shared between processes, which is exactly why it is
    replaced at Phase 2 rather than grown.
    """

    def __init__(self) -> None:
        self._published: list[EventEnvelope] = []
        self._sequences: dict[UUID | None, int] = {}

    async def publish(self, event: Event, *, investigation_id: UUID | None = None) -> EventEnvelope:
        """Assign the next sequence for this investigation and record the event."""
        next_sequence = self._sequences.get(investigation_id, 0)
        self._sequences[investigation_id] = next_sequence + 1

        envelope = EventEnvelope(
            id=uuid4(),
            emitted_at=datetime.now(UTC),
            event=event,
            sequence=next_sequence,
        )
        self._published.append(envelope)
        return envelope

    @property
    def published(self) -> list[EventEnvelope]:
        """Everything published so far, in order. Read-only view for tests."""
        return list(self._published)

    def clear(self) -> None:
        """Forget everything. Tests use this; production has no reason to."""
        self._published.clear()
        self._sequences.clear()


# TODO: Phase 5 - replace the in-memory implementation with a durable bus.
#
# The Protocol is the seam, so this is a substitution rather than a rewrite.
#
# Durability buys nothing until a run OUTLIVES A PROCESS, and none does: every
# investigation completes inside one `investigate()` call. ADR 0007's deferred
# actions are the first thing that changes that - a chaos experiment or a CI
# bisect runs for tens of minutes - and that is Phase 5 with Temporal.
