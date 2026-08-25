"""Where Investigations live between the run that made them and the read that wants them.

A Protocol with two implementations, following `core/bus.py` exactly: the
in-memory one is for tests and development, the Postgres one is what the API
actually reads from.

WHY POSTGRES NOW RATHER THAN A DICT
------------------------------------
"The Investigation persists and is retrievable" is not a claim an in-memory
store can be gated on. A test in one process cannot tell a dict from a database,
so a gate written against a dict asserts retrievability and calls it
persistence. `tests/integration/test_flow_one.py` reads back through a **second
store instance on a fresh connection**, which fails against a dict and passes
only if the row left the process.

The schema is created on first use rather than migrated. There is no migration
tool in this repository yet, and introducing one is a decision with its own
tradeoffs - so this creates its table and says so, instead of pretending a
migration story exists. One table, one JSONB document: the contract is already
the schema, and duplicating its shape in columns would create two definitions to
keep in step.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]  # no py.typed marker upstream

from core.config import get_settings
from core.contracts.investigation import Investigation

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


class InvestigationStore(Protocol):
    """What Zeus and the API depend on. Implementations vary; this does not."""

    async def save(self, investigation: Investigation) -> None:
        """Insert or replace. Zeus saves at every state change, not only at the end."""
        ...

    async def get(self, investigation_id: UUID) -> Investigation | None:
        """The Investigation, or None. Absence is a legitimate answer, not an error."""
        ...

    async def recent(self, limit: int = 20) -> list[Investigation]:
        """Newest first."""
        ...


class InMemoryInvestigationStore:
    """A store that remembers everything, for unit tests.

    Not durable and not shared between processes - which is why the live gate
    does not use it. See the module docstring.
    """

    def __init__(self) -> None:
        self._saved: dict[UUID, Investigation] = {}

    async def save(self, investigation: Investigation) -> None:
        self._saved[investigation.id] = investigation

    async def get(self, investigation_id: UUID) -> Investigation | None:
        return self._saved.get(investigation_id)

    async def recent(self, limit: int = 20) -> list[Investigation]:
        ordered = sorted(self._saved.values(), key=lambda i: i.created_at, reverse=True)
        return ordered[:limit]


class PostgresInvestigationStore:
    """The real one. Owns its pool, creates its table on first use."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _dsn()
        self._pool: asyncpg.Pool | None = None

    async def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
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


def _dsn() -> str:
    """Built from settings, like every other connection in this repository.

    Reading `POSTGRES_*` here rather than accepting a URL keeps the credential
    out of call sites, and keeps one place that knows where the database is.
    """
    postgres = get_settings().postgres
    password = postgres.password.get_secret_value() if postgres.password else ""
    credentials = f"{postgres.user}:{password}@" if password else f"{postgres.user}@"
    return f"postgresql://{credentials}{postgres.host}:{postgres.port}/{postgres.db}"
