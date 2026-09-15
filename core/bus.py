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

import contextlib
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from core.contracts.events import DeliveryGuarantee, Event, EventEnvelope

logger = logging.getLogger(__name__)

#: What a subscriber is handed. Synchronous on purpose: the one consumer today
#: puts the envelope on an asyncio.Queue, which is a synchronous call, and a
#: coroutine here would need the bus to own a task per subscriber.
Subscriber = Callable[[EventEnvelope], None]

#: Called to stop receiving. Returned by `subscribe` so a caller that opened a
#: subscription is the one holding the means to close it.
Unsubscribe = Callable[[], None]


class EventBus(Protocol):
    """What the rest of Pantheon depends on. Implementations vary; this does not."""

    #: What this implementation promises. Declared rather than assumed, so a
    #: consumer needing more than a bus offers fails at wiring time instead of
    #: discovering it as a gap during an incident.
    guarantee: DeliveryGuarantee

    async def publish(self, event: Event, *, investigation_id: UUID | None = None) -> EventEnvelope:
        """Wrap `event` in an envelope, assign its sequence, and deliver it."""
        ...

    def subscribe(self, investigation_id: UUID, subscriber: Subscriber) -> Unsubscribe:
        """Receive every envelope published for one investigation, from now on.

        From now on, not from the start: a subscriber that wants the past
        reads the store - the AG-UI endpoint sends a snapshot for exactly this
        reason - and a bus that replayed history to late subscribers would be
        a second copy of the store with weaker guarantees.

        THIS IS THE SEAM THE STREAM WAS MISSING
        -----------------------------------------
        `api/agui/endpoint.py` read `app.state.agui_subscribe` and nothing but
        a test ever set it. In the running app the stream sent its opening
        snapshot and closed, the dashboard's hook read that as a dropped
        connection, and every open detail page reconnected every one to thirty
        seconds for as long as it stayed open. The docstring on the endpoint
        called this "a subscription that does not exist" and it was right.
        """
        ...


class InMemoryEventBus:
    """An event bus that remembers everything, for development and tests.

    Not durable and not shared between processes, which is exactly why it is
    replaced at Phase 2 rather than grown.
    """

    #: AT_MOST_ONCE, and that is the truth rather than a placeholder. Nothing is
    #: persisted, nothing is acknowledged, and a process that dies takes every
    #: event with it. Declaring anything stronger would let a consumer believe
    #: a picture was complete when the bus cannot say so - and `ReplayCursor`
    #: exists precisely because that has to be detectable at the reader.
    guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_MOST_ONCE

    def __init__(self) -> None:
        self._published: list[EventEnvelope] = []
        self._sequences: dict[UUID | None, int] = {}
        self._subscribers: dict[UUID, list[Subscriber]] = defaultdict(list)

    async def publish(self, event: Event, *, investigation_id: UUID | None = None) -> EventEnvelope:
        """Assign the next sequence for this investigation, record it, fan it out."""
        next_sequence = self._sequences.get(investigation_id, 0)
        self._sequences[investigation_id] = next_sequence + 1

        envelope = EventEnvelope(
            id=uuid4(),
            emitted_at=datetime.now(UTC),
            event=event,
            sequence=next_sequence,
        )
        self._published.append(envelope)

        if investigation_id is not None:
            # A copy, because a subscriber may unsubscribe itself while being
            # called and mutating the list under the loop skips its neighbour.
            for subscriber in list(self._subscribers.get(investigation_id, ())):
                try:
                    subscriber(envelope)
                except Exception:
                    # A dead subscriber - a client that went away mid-event -
                    # must not fail the run that was publishing. The run is
                    # the thing that matters; the subscriber was watching it.
                    logger.exception("subscriber failed on %s", envelope.event.type)
        return envelope

    def subscribe(self, investigation_id: UUID, subscriber: Subscriber) -> Unsubscribe:
        """In-process fan-out. Correct for as long as Zeus runs in this process.

        It does today: `api/routers/_runs.py` runs an investigation as a
        BackgroundTask of the API that accepted it. The moment a separate worker
        runs it, this bus cannot see the events and the stream goes quiet again
        - which is the trigger for the durable, shared implementation the TODO
        below names, and the reason `guarantee` still says AT_MOST_ONCE.
        """
        self._subscribers[investigation_id].append(subscriber)

        def unsubscribe() -> None:
            # Already gone is fine: unsubscribing twice is not an error.
            with contextlib.suppress(ValueError):
                self._subscribers[investigation_id].remove(subscriber)

        return unsubscribe

    @property
    def published(self) -> list[EventEnvelope]:
        """Everything published so far, in order. Read-only view for tests."""
        return list(self._published)

    def clear(self) -> None:
        """Forget everything. Tests use this; production has no reason to."""
        self._published.clear()
        self._sequences.clear()


# TODO: Phase 5 - replace the in-memory implementation with a durable, shared bus.
#
# The trigger is a second process. `subscribe` above fans out in-process, which
# is correct while the API runs every investigation as its own BackgroundTask
# and wrong the moment `core/workflows/worker.py` runs one instead: the API's
# bus would never see the worker's events, and the AG-UI stream would go quiet
# exactly the way it was quiet before `subscribe` existed. Redis is already in
# the stack for that day.
#
# The Protocol is the seam, so this is a substitution rather than a rewrite.
#
# Durability buys nothing until a run OUTLIVES A PROCESS, and none does: every
# investigation completes inside one `investigate()` call. ADR 0007's deferred
# actions are the first thing that changes that - a chaos experiment or a CI
# bisect runs for tens of minutes - and that is Phase 5 with Temporal.
