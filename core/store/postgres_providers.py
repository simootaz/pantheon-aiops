"""The Postgres-backed provider store: driver code, and nothing else.

WHY THIS IS ITS OWN MODULE
----------------------------
Every line here needs a live database, so none of it is reachable from the unit
job, and the per-module coverage floor would fail on it forever. The alternative
- exempting `core/store/providers.py` whole - would have taken `StoredProvider`,
`InMemoryProviderStore`, `row_to_stored` and `config_from_input` out from under
the floor too, and those are exactly the pieces where a mistake leaks a key.

Same boundary, same reason, as the `investigations.py` / `postgres.py` split:
the exemption is drawn where the claim "this cannot be unit-tested" becomes
true, not where the module happened to end. `row_to_stored` stays behind
because it takes a mapping and touches no connection.

Covered by `make test-providers`, which runs the whole surface against a real
database - see tests/integration/test_provider_store.py.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]  # no py.typed marker upstream

from core.cerberus.store.envelope import Sealed, open_sealed, seal
from core.contracts.llm import ProviderConfig, Tier
from core.store.postgres import SCHEMA_PROVIDERS
from core.store.providers import StoredProvider, row_to_stored

#: Every read selects the same shape, and `row_to_stored` depends on it. Written
#: once so a column added to one query cannot go missing from another.
COLUMNS = "id, config, sealed_key, tiers, created_at, updated_at"


class PostgresProviderStore:
    """The real one. Keys are sealed before they ever reach a column.

    `seal()` is called in this module rather than by the caller so there is no
    path that writes to `sealed_key` with anything but ciphertext.
    """

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool

    async def _ready(self) -> asyncpg.Pool:
        if self._pool is None:
            from core.store.postgres import PostgresInvestigationStore

            self._pool = await PostgresInvestigationStore()._ready()
            async with self._pool.acquire() as connection:
                await connection.execute(SCHEMA_PROVIDERS)
        return self._pool

    async def create(self, config: ProviderConfig, *, api_key: str | None = None) -> StoredProvider:
        pool = await self._ready()
        sealed = seal(api_key) if api_key else None
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                f"""
                INSERT INTO llm_providers (id, config, sealed_key, tiers)
                VALUES ($1, $2, $3, $4)
                RETURNING {COLUMNS}
                """,
                uuid4(),
                config.model_dump_json(),
                json.dumps(sealed.as_dict()) if sealed else None,
                json.dumps({}),
            )
        return row_to_stored(row)

    async def update(
        self,
        provider_id: UUID,
        *,
        config: ProviderConfig | None = None,
        api_key: str | None = None,
        tiers: dict[Tier, str] | None = None,
    ) -> StoredProvider | None:
        """`api_key=None` keeps the stored key; `api_key=""` removes it.

        The distinction matters: editing a display name must not silently
        de-credential a working provider, and there has to be some way to revoke
        one. A single "falsy means clear" rule would have made the first
        impossible to avoid.
        """
        pool = await self._ready()
        async with pool.acquire() as connection:
            existing = await connection.fetchrow(
                f"SELECT {COLUMNS} FROM llm_providers WHERE id = $1", provider_id
            )
            if existing is None:
                return None

            sealed_json = existing["sealed_key"]
            if api_key is not None:
                sealed_json = json.dumps(seal(api_key).as_dict()) if api_key else None

            row = await connection.fetchrow(
                f"""
                UPDATE llm_providers
                   SET config = $2, sealed_key = $3, tiers = $4, updated_at = now()
                 WHERE id = $1
                RETURNING {COLUMNS}
                """,
                provider_id,
                config.model_dump_json() if config else existing["config"],
                sealed_json,
                json.dumps({tier.value: model for tier, model in tiers.items()})
                if tiers is not None
                else existing["tiers"],
            )
        return row_to_stored(row)

    async def get(self, provider_id: UUID) -> StoredProvider | None:
        pool = await self._ready()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {COLUMNS} FROM llm_providers WHERE id = $1", provider_id
            )
        return row_to_stored(row) if row else None

    async def list(self) -> list[StoredProvider]:
        pool = await self._ready()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT {COLUMNS} FROM llm_providers ORDER BY created_at"
            )
        return [row_to_stored(row) for row in rows]

    async def delete(self, provider_id: UUID) -> bool:
        pool = await self._ready()
        async with pool.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM llm_providers WHERE id = $1", provider_id
            )
        # asyncpg returns the command tag, e.g. "DELETE 1" or "DELETE 0".
        return str(result).endswith("1")

    async def reveal_key(self, provider_id: UUID) -> str | None:
        """The only path to a plaintext key. Named so it can be grepped for."""
        pool = await self._ready()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT sealed_key FROM llm_providers WHERE id = $1", provider_id
            )
        if row is None or row["sealed_key"] is None:
            return None
        return open_sealed(Sealed.from_dict(json.loads(row["sealed_key"])))
