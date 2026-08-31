"""Where configured LLM providers live, with their keys sealed.

ADR 0004 is explicit that a provider key is a Cerberus credential: encrypted at
rest, never in plaintext config, never in a log or a `ResolutionRecord`. This
store is what makes a key pasted into the settings UI obey that - it seals on
write and only unseals for the one caller that needs to make a request.

THE KEY LEAVES BY EXACTLY ONE DOOR
------------------------------------
`get` and `list` return a `StoredProvider` whose `has_key` is a boolean. Nothing
on that object can be rendered into a response and leak anything, which is the
property that matters when the same object is passed to a template, a log line
and a JSON encoder by three different people.

`reveal_key` is the only way to the plaintext, it is a separate call, and it
says what it is. A reader of `api/routers/providers.py` can see every place a
key could escape by searching for one name.

WHERE THE POSTGRES IMPLEMENTATION IS
--------------------------------------
`core/store/postgres_providers.py`, because every line of it needs a live
database and would sit permanently under the per-module coverage floor. What
remains here - the Protocol, the in-memory store that seals exactly as the real
one does, `row_to_stored` and `config_from_input` - is all reachable from a unit
test, and is where a mistake would leak a key.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from core.cerberus.store.envelope import Sealed, open_sealed, seal
from core.contracts.llm import AuthMode, Dialect, ProviderConfig, Tier


@dataclass(frozen=True)
class StoredProvider:
    """A configured provider as everything except the request path sees it.

    Deliberately not `ProviderConfig`: that contract has no notion of a stored
    secret, and adding one would put a key-shaped field on the model that flows
    through codegen into Go and TypeScript.
    """

    id: UUID
    config: ProviderConfig
    has_key: bool
    tiers: dict[Tier, str]
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "provider_id": self.config.id,
            "display_name": self.config.display_name,
            "dialect": self.config.dialect.value,
            "base_url": self.config.base_url,
            "auth_mode": self.config.auth_mode.value,
            "enabled": self.config.enabled,
            "manual_models": list(self.config.manual_models),
            "has_key": self.has_key,
            "tiers": {tier.value: model for tier, model in self.tiers.items()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ProviderStore(Protocol):
    """What the settings API depends on."""

    async def create(
        self, config: ProviderConfig, *, api_key: str | None = None
    ) -> StoredProvider: ...

    async def update(
        self,
        provider_id: UUID,
        *,
        config: ProviderConfig | None = None,
        api_key: str | None = None,
        tiers: dict[Tier, str] | None = None,
    ) -> StoredProvider | None: ...

    async def get(self, provider_id: UUID) -> StoredProvider | None: ...

    async def list(self) -> list[StoredProvider]: ...

    async def delete(self, provider_id: UUID) -> bool: ...

    async def reveal_key(self, provider_id: UUID) -> str | None: ...


class InMemoryProviderStore:
    """For unit tests. Seals exactly as the real one does.

    Sealing here too, rather than holding plaintext, so a test cannot pass
    against an in-memory store and fail against Postgres because one of them
    encrypts and the other does not.
    """

    def __init__(self, master: bytes | None = None) -> None:
        self._master = master
        self._rows: dict[UUID, tuple[StoredProvider, Sealed | None]] = {}

    async def create(self, config: ProviderConfig, *, api_key: str | None = None) -> StoredProvider:
        now = datetime.now(tz=UTC)
        sealed = seal(api_key, master=self._master) if api_key else None
        stored = StoredProvider(
            id=uuid4(),
            config=config,
            has_key=sealed is not None,
            tiers={},
            created_at=now,
            updated_at=now,
        )
        self._rows[stored.id] = (stored, sealed)
        return stored

    async def update(
        self,
        provider_id: UUID,
        *,
        config: ProviderConfig | None = None,
        api_key: str | None = None,
        tiers: dict[Tier, str] | None = None,
    ) -> StoredProvider | None:
        row = self._rows.get(provider_id)
        if row is None:
            return None
        current, sealed = row
        if api_key is not None:
            sealed = seal(api_key, master=self._master) if api_key else None
        updated = StoredProvider(
            id=current.id,
            config=config or current.config,
            has_key=sealed is not None,
            tiers=tiers if tiers is not None else current.tiers,
            created_at=current.created_at,
            updated_at=datetime.now(tz=UTC),
        )
        self._rows[provider_id] = (updated, sealed)
        return updated

    async def get(self, provider_id: UUID) -> StoredProvider | None:
        row = self._rows.get(provider_id)
        return row[0] if row else None

    async def list(self) -> list[StoredProvider]:
        return [stored for stored, _ in self._rows.values()]

    async def delete(self, provider_id: UUID) -> bool:
        return self._rows.pop(provider_id, None) is not None

    async def reveal_key(self, provider_id: UUID) -> str | None:
        row = self._rows.get(provider_id)
        if row is None or row[1] is None:
            return None
        return open_sealed(row[1], master=self._master)


def row_to_stored(row: Any) -> StoredProvider:
    """Turn one database row into a `StoredProvider`.

    Here rather than beside the SQL because it takes a mapping and opens no
    connection - the same reason `dsn()` stayed out of the exempt store module.
    """
    tiers_raw = json.loads(row["tiers"]) if row["tiers"] else {}
    return StoredProvider(
        id=row["id"],
        config=ProviderConfig.model_validate_json(row["config"]),
        has_key=row["sealed_key"] is not None,
        tiers={Tier(key): value for key, value in tiers_raw.items()},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def config_from_input(
    *,
    provider_id: str,
    display_name: str,
    dialect: Dialect,
    base_url: str,
    auth_mode: AuthMode,
    manual_models: list[str] | None = None,
    enabled: bool = True,
) -> ProviderConfig:
    """Build a `ProviderConfig` from what a settings form supplies.

    `secret_ref` is set to the stored-credential marker rather than an env var
    name: the key lives in this store now, and pointing at an environment
    variable that does not exist would be a worse lie than pointing at nothing.
    """
    return ProviderConfig(
        id=provider_id,
        display_name=display_name,
        dialect=dialect,
        base_url=base_url,
        auth_mode=auth_mode,
        secret_ref="cerberus://llm_providers" if auth_mode is not AuthMode.NONE else None,
        manual_models=manual_models or [],
        enabled=enabled,
    )
