"""Fakes for agent tests: a context, a bus, and a connector that misbehaves.

The last one matters most. Every agent has to degrade honestly when a connector
is unreachable, and a fake that only ever succeeds tests the happy path of a
mechanism whose whole purpose is the unhappy one.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from agents._base.base_agent import AgentContext
from core.bus import InMemoryEventBus
from core.contracts.investigation import Trigger, TriggerKind


def a_trigger(source: str = "test", title: str = "synthetic trigger") -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source=source,
        title=title,
    )


def a_context(
    *,
    investigation_id: UUID | None = None,
    minutes: float = 30.0,
    **params: Any,
) -> AgentContext:
    """A context over a fixed window, so ids are reproducible across a test run."""
    end = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    return AgentContext(
        investigation_id=investigation_id or uuid4(),
        trigger=a_trigger(),
        window_start=end - timedelta(minutes=minutes),
        window_end=end,
        params=dict(params),
    )


class RecordingBus(InMemoryEventBus):
    """The real in-memory bus, with a lookup by event type.

    Subclassed rather than reimplemented on purpose. A hand-written fake bus is
    free to assign sequence numbers differently, or to accept an envelope the
    real one would reject - which is what the first version of this did, and the
    difference only showed when a real Finding went through it.
    """

    def of_type(self, name: str) -> list[Any]:
        return [
            envelope.event
            for envelope in self.published
            if getattr(envelope.event, "type", "") == name
        ]


class UnreachableConnector:
    """A tool that always fails, the way a connector that is down actually does."""

    def __init__(self, message: str = "connection refused") -> None:
        self.message = message
        self.attempts = 0

    async def __call__(self, **_kwargs: Any) -> Any:
        self.attempts += 1
        raise ConnectionError(self.message)


class CountingConnector:
    """A tool that succeeds and records how it was called."""

    def __init__(self, result: Any = None) -> None:
        self.result = result if result is not None else {"data": {"result": []}}
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.result
