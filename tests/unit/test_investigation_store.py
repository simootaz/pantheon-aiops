"""The store's logic that has no database in it.

`core/store/postgres.py` is exempt from the coverage floor because every line of
it needs a live Postgres. Nothing in *this* module does, which is why the split
exists - see `tests/unit/test_coverage_exemptions.py`.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.store import investigations as store_module
from core.store.investigations import (
    InMemoryInvestigationStore,
    PostgresNotConfigured,
    dsn,
)


def _investigation(created_at: datetime) -> Investigation:
    return Investigation(
        id=uuid4(),
        state=InvestigationState.PENDING,
        trigger=Trigger(
            kind=TriggerKind.ALERT,
            received_at=created_at,
            source="alertmanager",
            title="test",
        ),
        created_at=created_at,
    )


# --- the in-memory store ------------------------------------------------------


@pytest.mark.asyncio
async def test_absence_is_an_answer_not_an_error() -> None:
    store = InMemoryInvestigationStore()
    assert await store.get(uuid4()) is None


@pytest.mark.asyncio
async def test_saving_the_same_id_twice_replaces_rather_than_duplicates() -> None:
    """Zeus saves at every state change, so the second write is the normal case."""
    store = InMemoryInvestigationStore()
    first = _investigation(datetime.now(UTC))
    await store.save(first)
    await store.save(first.model_copy(update={"state": InvestigationState.RUNNING}))

    assert len(await store.recent()) == 1
    stored = await store.get(first.id)
    assert stored is not None and stored.state is InvestigationState.RUNNING


@pytest.mark.asyncio
async def test_recent_is_newest_first_and_honours_its_limit() -> None:
    """Ordering is the whole contract of `recent`; a set would satisfy the rest."""
    now = datetime.now(UTC)
    store = InMemoryInvestigationStore()
    oldest, middle, newest = (
        _investigation(now - timedelta(minutes=10)),
        _investigation(now - timedelta(minutes=5)),
        _investigation(now),
    )
    for investigation in (middle, newest, oldest):
        await store.save(investigation)

    assert [i.id for i in await store.recent()] == [newest.id, middle.id, oldest.id]
    assert [i.id for i in await store.recent(limit=2)] == [newest.id, middle.id]
    assert await store.recent(limit=0) == []


# --- the connection string, which touches no database -------------------------


class _Postgres:
    def __init__(self, password: SecretStr | None) -> None:
        self.host, self.port, self.db, self.user = "db.internal", 6432, "pantheon", "zeus"
        self.password = password


def _settings(monkeypatch: pytest.MonkeyPatch, password: SecretStr | None) -> None:
    class _Settings:
        postgres = _Postgres(password)

    monkeypatch.setattr(store_module, "get_settings", lambda: _Settings())


def test_a_dsn_carries_every_part_of_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, SecretStr("s3cret"))
    assert dsn() == "postgresql://zeus:s3cret@db.internal:6432/pantheon"


def test_a_missing_password_is_named_rather_than_left_to_the_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this branch already shipped once, now asserted.

    With no password the DSN was built without one, and asyncpg answered
    `InvalidPasswordError: password authentication failed` - which describes a
    WRONG password when the problem is a MISSING one. Those have different fixes
    and the first sends you to the wrong place. It sent me there.
    """
    _settings(monkeypatch, None)
    with pytest.raises(PostgresNotConfigured, match="POSTGRES_PASSWORD is not set"):
        dsn()


def test_the_refusal_says_where_the_value_lives(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal a reader cannot act on is a refusal that costs them an hour."""
    _settings(monkeypatch, None)
    try:
        dsn()
    except PostgresNotConfigured as refusal:
        message = str(refusal)
    assert "deploy/compose/.env" in message
    assert ".env" in message and "core/config.py" in message


def test_the_protocol_and_the_in_memory_store_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """The in-memory store must actually satisfy the Protocol it stands in for.

    Structural typing means a missing method is not an error until someone calls
    it - at which point the substitute has already been trusted.
    """
    store: Any = InMemoryInvestigationStore()
    for method in ("save", "get", "recent"):
        assert callable(getattr(store, method, None)), f"in-memory store has no {method}"
