"""Where Investigations live between the run that made them and the read that wants them.

A Protocol with two implementations, following `core/bus.py` exactly: the
in-memory one is here, and the Postgres one is in `core/store/postgres.py` -
split because that module is exempt from the coverage floor and this one must
not be. `dsn()` builds a connection string from settings and touches no
database; exempting it along with the driver code would have left the function
that already got this wrong once unprotected.

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

from core.config import get_settings
from core.contracts.investigation import Investigation


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


class PostgresNotConfigured(RuntimeError):
    """No password is configured, so no connection can be attempted.

    Raised here rather than letting asyncpg fail, because the driver's message -
    `InvalidPasswordError: password authentication failed` - describes a wrong
    password and this is a missing one. The two have different fixes and the
    first sends you looking in the wrong place, which is where it sent me.
    """


def dsn() -> str:
    """Built from settings, like every other connection in this repository.

    Reading `POSTGRES_*` here rather than accepting a URL keeps the credential
    out of call sites, and keeps one place that knows where the database is.
    """
    postgres = get_settings().postgres
    if postgres.password is None:
        raise PostgresNotConfigured(
            "POSTGRES_PASSWORD is not set, so the investigation store cannot connect. "
            f"The compose stack's value lives in deploy/compose/.env (user "
            f"{postgres.user!r}, database {postgres.db!r}); export it, or put it in a "
            "repository-root .env, which is the file core/config.py reads."
        )
    return (
        f"postgresql://{postgres.user}:{postgres.password.get_secret_value()}"
        f"@{postgres.host}:{postgres.port}/{postgres.db}"
    )
