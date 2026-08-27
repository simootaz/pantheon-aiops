"""The Postgres-backed Investigation store.

SEPARATE FROM ITS PROTOCOL, AND THE SPLIT IS THE POINT
-------------------------------------------------------
Every path in this module needs a live database. `make test-flow-one` executes
all of them - the pool being created, the table being made, save, get, recent,
and close - and CI's Python job does not start a Postgres, so none of it is
covered there.

That earns this module an entry in `tests/coverage_floor.py`'s exemption list,
and the exemption is why it is a separate file. `_dsn()` and the in-memory store
next door are pure logic with no database in them, and a whole-module exemption
would have swallowed both. `_dsn()` in particular was already wrong once - it
built a passwordless DSN and produced a driver error describing the wrong
problem - which is exactly the kind of thing a coverage floor is for.

**The boundary is drawn where the exemption's claim becomes true**, not where
the module happened to end. Everything here is covered by the flow-one gate;
nothing here is covered by nothing.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from uuid import UUID

import asyncpg  # type: ignore[import-untyped]  # no py.typed marker upstream

from core.contracts.investigation import Investigation
from core.store.investigations import dsn

#: One table, created on first use. `document` is the contract verbatim, so a
#: field added to `Investigation` needs no migration to be stored - only to be
#: queried by, which nothing does yet.
SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id          UUID PRIMARY KEY,
    state       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    document    JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS investigations_created_at_idx
    ON investigations (created_at DESC);
"""

#: Configured LLM providers. `sealed_key` is an envelope-encrypted record and
#: never a plaintext key - see `core/cerberus/store/envelope.py`. It is nullable
#: because a local provider needs no credential at all, and a NULL says that
#: more honestly than an empty string.
SCHEMA_PROVIDERS = """
CREATE TABLE IF NOT EXISTS llm_providers (
    id          UUID PRIMARY KEY,
    config      JSONB       NOT NULL,
    sealed_key  JSONB,
    tiers       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresInvestigationStore:
    """The real one. Owns its pool, creates its table on first use."""

    def __init__(self, connection_string: str | None = None) -> None:
        # The DSN is resolved on first use, not here. Constructing the store is
        # what the app factory does at import time, and a missing password is a
        # reason to fail a query rather than a reason the process cannot start -
        # every unit test that builds the app would otherwise need a database.
        self._configured = connection_string
        self._pool: asyncpg.Pool | None = None

    async def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            connection_string = self._configured or dsn()
            self._pool = await asyncpg.create_pool(connection_string, min_size=1, max_size=4)
            async with self._pool.acquire() as connection:
                await connection.execute(SCHEMA)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save(self, investigation: Investigation) -> None:
        pool = await self._ready()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO investigations (id, state, created_at, updated_at, document)
                VALUES ($1, $2, $3, now(), $4)
                ON CONFLICT (id) DO UPDATE
                   SET state = EXCLUDED.state,
                       updated_at = now(),
                       document = EXCLUDED.document
                """,
                investigation.id,
                investigation.state.value,
                investigation.created_at,
                investigation.model_dump_json(),
            )

    async def get(self, investigation_id: UUID) -> Investigation | None:
        pool = await self._ready()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT document FROM investigations WHERE id = $1", investigation_id
            )
        return Investigation.model_validate_json(row["document"]) if row else None

    async def recent(self, limit: int = 20) -> list[Investigation]:
        pool = await self._ready()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT document FROM investigations ORDER BY created_at DESC LIMIT $1", limit
            )
        return [Investigation.model_validate_json(row["document"]) for row in rows]
