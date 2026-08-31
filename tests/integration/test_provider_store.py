"""The Postgres provider store, against a real database.

WHY THIS GATE EXISTS
----------------------
`core/store/postgres_providers.py` is exempt from the per-module coverage floor
because every line of it needs a live database. An exemption is a module CI
stops protecting, so it is only honest if something else protects it. This is
that something. It executes the whole surface: schema creation, create, get,
list, update, delete and reveal.

WHAT IT ASSERTS THAT A UNIT TEST CANNOT
-----------------------------------------
That the key in the `sealed_key` column is ciphertext. A unit test reads a
sealed record back through the object that sealed it; this reads the raw column
with a second connection and greps it for the plaintext. That is the assertion
worth having a database for.

Run with:  make test-providers

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from core.cerberus.store.master_key import KEY_BYTES
from core.contracts.llm import AuthMode, Dialect, Tier
from core.store.postgres import PostgresInvestigationStore
from core.store.postgres_providers import PostgresProviderStore
from core.store.providers import config_from_input

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SECRET = "gsk_integration_key_that_must_stay_sealed"


@pytest.fixture(scope="module", autouse=True)
def master_key() -> None:
    """A throwaway master key for this run.

    Set here rather than read from `.env`, so the gate does not depend on a
    developer having generated one, and so a failure means the code is wrong
    rather than the environment being unconfigured.
    """
    os.environ["CERBERUS_MASTER_KEY"] = base64.b64encode(os.urandom(KEY_BYTES)).decode()
    from core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
async def store() -> AsyncIterator[PostgresProviderStore]:
    """A store on a live pool, with its rows removed afterwards."""
    subject = PostgresProviderStore()
    try:
        pool = await subject._ready()
    except Exception as unreachable:  # pragma: no cover - environment, not logic
        pytest.fail(
            f"Postgres is not reachable ({unreachable}). This gate asserts against "
            "a real database by design - start it with: make up"
        )
    yield subject
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM llm_providers")


def _config(provider_id: str = "groq", auth: AuthMode = AuthMode.BEARER) -> object:
    return config_from_input(
        provider_id=provider_id,
        display_name="Groq",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="https://api.groq.com/openai/v1",
        auth_mode=auth,
        manual_models=["openai/gpt-oss-20b"],
    )


async def test_the_column_holds_ciphertext_and_not_the_key(
    store: PostgresProviderStore,
) -> None:
    """The reason this gate needs a database.

    Read back on a second connection, out of the store entirely: a store that
    forgot to seal would still pass a test that asks the store for the value.
    """
    stored = await store.create(_config(), api_key=SECRET)  # type: ignore[arg-type]

    pool = await PostgresInvestigationStore()._ready()
    async with pool.acquire() as connection:
        raw = await connection.fetchval(
            "SELECT sealed_key::text FROM llm_providers WHERE id = $1", stored.id
        )

    assert raw is not None, "no sealed key was written"
    assert SECRET not in raw, "the plaintext key is in the database"
    assert "gsk_" not in raw
    assert set(json.loads(raw)) == {"version", "wrapped_key", "key_nonce", "ciphertext", "nonce"}

    assert await store.reveal_key(stored.id) == SECRET


async def test_the_full_lifecycle_survives_a_round_trip(store: PostgresProviderStore) -> None:
    stored = await store.create(_config(), api_key=SECRET)  # type: ignore[arg-type]

    fetched = await store.get(stored.id)
    assert fetched is not None
    assert fetched.config.id == "groq"
    assert fetched.has_key is True
    assert fetched.tiers == {}

    assert [row.id for row in await store.list()] == [stored.id]

    bound = await store.update(stored.id, tiers={Tier.CHEAP: "openai/gpt-oss-20b"})
    assert bound is not None
    assert bound.tiers == {Tier.CHEAP: "openai/gpt-oss-20b"}, (
        "tiers did not survive the JSON column round trip"
    )
    assert bound.has_key is True, "binding a tier dropped the key"

    assert await store.delete(stored.id) is True
    assert await store.get(stored.id) is None
    assert await store.delete(stored.id) is False, "deleting nothing reported success"


async def test_an_edit_that_omits_the_key_keeps_it(store: PostgresProviderStore) -> None:
    """The failure this prevents: renaming a provider silently de-credentials it."""
    stored = await store.create(_config(), api_key=SECRET)  # type: ignore[arg-type]

    renamed = await store.update(stored.id, config=_config(provider_id="groq-prod"))  # type: ignore[arg-type]

    assert renamed is not None
    assert renamed.config.id == "groq-prod"
    assert renamed.has_key is True
    assert await store.reveal_key(stored.id) == SECRET


async def test_an_empty_key_clears_the_stored_one(store: PostgresProviderStore) -> None:
    """Distinct from omitting it - there has to be a way to revoke a credential."""
    stored = await store.create(_config(), api_key=SECRET)  # type: ignore[arg-type]

    cleared = await store.update(stored.id, api_key="")

    assert cleared is not None
    assert cleared.has_key is False
    assert await store.reveal_key(stored.id) is None


async def test_a_provider_with_no_credential_stores_no_key(store: PostgresProviderStore) -> None:
    stored = await store.create(_config(provider_id="local", auth=AuthMode.NONE))  # type: ignore[arg-type]

    fetched = await store.get(stored.id)
    assert fetched is not None
    assert fetched.has_key is False
    assert await store.reveal_key(stored.id) is None


async def test_operations_on_a_missing_row_return_none(store: PostgresProviderStore) -> None:
    missing = uuid4()

    assert await store.get(missing) is None
    assert await store.update(missing, api_key=SECRET) is None
    assert await store.reveal_key(missing) is None
    assert await store.delete(missing) is False
