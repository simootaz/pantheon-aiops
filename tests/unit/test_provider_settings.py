"""Provider CRUD, the model picker, and the guarantee that a key never comes back.

The security assertions here are the point of the file. Everything else is
plumbing that can be re-derived; a leaked provider key cannot be un-leaked.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core.cerberus.store.envelope import (
    DecryptionFailed,
    Sealed,
    open_sealed,
    rewrap,
    seal,
)
from core.cerberus.store.master_key import MasterKeyMalformed, MasterKeyUnavailable, resolve
from core.contracts.llm import AuthMode, Capability, Dialect, Tier
from core.llm.provider import ProviderError
from core.llm.providers.chat_completions import ChatCompletionsProvider
from core.store.investigations import InMemoryInvestigationStore
from core.store.providers import InMemoryProviderStore, config_from_input

SECRET = "gsk_a_key_that_must_never_be_returned"
MASTER = os.urandom(32)


@pytest.fixture
def store() -> InMemoryProviderStore:
    return InMemoryProviderStore(master=MASTER)


@pytest.fixture
def client(store: InMemoryProviderStore) -> Iterator[TestClient]:
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=store,
    )
    with TestClient(app) as test_client:
        yield test_client


def _payload(**overrides: Any) -> dict[str, Any]:
    body = {
        "provider_id": "groq",
        "display_name": "Groq",
        "dialect": "chat_completions",
        "base_url": "https://api.groq.com/openai/v1",
        "auth_mode": "bearer",
        "api_key": SECRET,
    }
    body.update(overrides)
    return body


def _stub_models(monkeypatch: pytest.MonkeyPatch, models: list[str]) -> None:
    """Answer /models without a socket.

    Unit tests must not reach a provider: on this platform a closed loopback
    port does not refuse promptly, so a real call fails by hanging.
    """

    async def listed(self: Any) -> list[str]:
        return models

    monkeypatch.setattr(ChatCompletionsProvider, "list_models", listed, raising=True)


# --- the envelope ---------------------------------------------------------------


def test_a_sealed_record_does_not_contain_the_plaintext() -> None:
    """The property everything else rests on."""
    sealed = seal(SECRET, master=MASTER)
    rendered = json.dumps(sealed.as_dict())

    assert SECRET not in rendered
    assert "gsk_" not in rendered
    assert open_sealed(sealed, master=MASTER) == SECRET


def test_the_wrong_master_key_fails_rather_than_returning_rubbish() -> None:
    sealed = seal(SECRET, master=MASTER)
    with pytest.raises(DecryptionFailed, match="did not authenticate"):
        open_sealed(sealed, master=os.urandom(32))


def test_a_tampered_ciphertext_is_refused() -> None:
    """AES-GCM authenticates, so an edited record must not decrypt at all."""
    sealed = seal(SECRET, master=MASTER)
    flipped = Sealed(**{**sealed.as_dict(), "ciphertext": seal("other", master=MASTER).ciphertext})
    with pytest.raises(DecryptionFailed):
        open_sealed(flipped, master=MASTER)


def test_every_seal_uses_a_fresh_data_key_and_nonce() -> None:
    """Nonce reuse under AES-GCM leaks the authentication key.

    Sealing the same plaintext twice must produce entirely different records, or
    a shared nonce space exists somewhere.
    """
    first, second = seal(SECRET, master=MASTER), seal(SECRET, master=MASTER)
    assert first.nonce != second.nonce
    assert first.key_nonce != second.key_nonce
    assert first.wrapped_key != second.wrapped_key
    assert first.ciphertext != second.ciphertext


def test_rotation_rewraps_without_touching_the_ciphertext() -> None:
    """The reason for the envelope: rotation is a metadata operation."""
    sealed = seal(SECRET, master=MASTER)
    new_master = os.urandom(32)
    rotated = rewrap(sealed, old_master=MASTER, new_master=new_master)

    assert rotated.ciphertext == sealed.ciphertext, "the credential was re-encrypted"
    assert rotated.wrapped_key != sealed.wrapped_key
    assert open_sealed(rotated, master=new_master) == SECRET
    with pytest.raises(DecryptionFailed):
        open_sealed(rotated, master=MASTER)


def test_an_old_format_version_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(DecryptionFailed, match="format version"):
        Sealed.from_dict({**seal(SECRET, master=MASTER).as_dict(), "version": 0})


def test_a_missing_master_key_says_how_to_make_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A generated fallback would make every stored credential unreadable after
    the next restart, and it would look like corruption rather than config."""
    import core.cerberus.store.master_key as module

    monkeypatch.setattr(module, "get_settings", lambda: _settings(None))
    with pytest.raises(MasterKeyUnavailable, match="CERBERUS_MASTER_KEY is not set"):
        resolve()


@pytest.mark.parametrize("value", ["not-base64!!", "c2hvcnQ="])
def test_a_malformed_master_key_is_refused_not_padded(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short key silently weakens every credential wrapped with it."""
    import core.cerberus.store.master_key as module

    monkeypatch.setattr(module, "get_settings", lambda: _settings(value))
    with pytest.raises(MasterKeyMalformed):
        resolve()


def _settings(master: str | None) -> Any:
    from pydantic import SecretStr

    class _Cerberus:
        master_key = SecretStr(master) if master is not None else None

    class _Settings:
        cerberus = _Cerberus()

    return _Settings()


# --- the key never comes back -----------------------------------------------------


def test_creating_a_provider_never_echoes_the_key(client: TestClient) -> None:
    """Not even masked. A masked key is still a key in a log and a screenshot."""
    response = client.post("/providers", json=_payload())

    assert response.status_code == 201, response.text
    body = response.text
    assert SECRET not in body
    assert "gsk_" not in body
    assert response.json()["has_key"] is True


def test_no_endpoint_returns_a_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every read path, checked together - a leak needs only one of them."""
    _stub_models(monkeypatch, ["m-1", "m-2"])
    created = client.post("/providers", json=_payload()).json()
    identifier = created["id"]

    for path in ("/providers", f"/providers/{identifier}", f"/providers/{identifier}/models"):
        text = client.get(path).text
        assert SECRET not in text, f"{path} leaked the key"
        assert "gsk_" not in text, f"{path} leaked something key-shaped"


def test_the_key_is_sealed_in_the_store_not_held_in_memory(
    client: TestClient, store: InMemoryProviderStore
) -> None:
    """The in-memory store seals too, so a test cannot pass here and fail on Postgres.

    Reaching into `_rows` is deliberate: the claim is about what is at rest, and
    there is no public accessor that would show it.
    """
    created = client.post("/providers", json=_payload()).json()

    at_rest = json.dumps(
        [
            {"stored": stored.as_dict(), "sealed": sealed.as_dict() if sealed else None}
            for stored, sealed in store._rows.values()
        ]
    )

    assert SECRET not in at_rest, "the plaintext key is sitting in the store"
    assert SECRET not in json.dumps(created)


@pytest.mark.asyncio
async def test_revealing_is_a_separate_named_call(store: InMemoryProviderStore) -> None:
    """One door to the plaintext, and it is greppable."""
    config = config_from_input(
        provider_id="groq",
        display_name="Groq",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="https://api.groq.com/openai/v1",
        auth_mode=AuthMode.BEARER,
    )
    stored = await store.create(config, api_key=SECRET)

    assert stored.has_key is True
    assert await store.reveal_key(stored.id) == SECRET
    assert "api_key" not in stored.as_dict()


# --- CRUD ---------------------------------------------------------------------------


def test_a_provider_can_be_added_listed_edited_and_removed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post("/providers", json=_payload()).json()
    identifier = created["id"]

    assert len(client.get("/providers").json()) == 1
    assert client.get(f"/providers/{identifier}").json()["display_name"] == "Groq"

    edited = client.put(
        f"/providers/{identifier}", json=_payload(display_name="Groq (prod)", api_key=None)
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["display_name"] == "Groq (prod)"
    assert edited.json()["has_key"] is True, (
        "omitting api_key on an edit dropped the stored key, so editing a display "
        "name would silently break the provider"
    )

    assert client.delete(f"/providers/{identifier}").status_code == 204
    assert client.get(f"/providers/{identifier}").status_code == 404
    assert client.delete(f"/providers/{identifier}").status_code == 404


def test_an_empty_key_removes_the_stored_one(client: TestClient) -> None:
    """Distinct from omitting it. One means "leave it", the other means "clear it"."""
    identifier = client.post("/providers", json=_payload()).json()["id"]
    cleared = client.put(f"/providers/{identifier}", json=_payload(api_key=""))
    assert cleared.json()["has_key"] is False


def test_a_credentialed_provider_without_a_key_is_refused(client: TestClient) -> None:
    response = client.post("/providers", json=_payload(api_key=None))
    assert response.status_code == 422
    assert "needs an api_key" in response.text


def test_a_local_provider_needs_no_key(client: TestClient) -> None:
    response = client.post(
        "/providers",
        json=_payload(
            provider_id="local-ollama",
            display_name="Local Ollama",
            base_url="http://localhost:11434/v1",
            auth_mode="none",
            api_key=None,
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["has_key"] is False


def test_a_dialect_with_no_adapter_is_refused_at_the_door(client: TestClient) -> None:
    """A provider stored now would look configured and fail when an agent needed it."""
    response = client.post("/providers", json=_payload(dialect="messages"))
    assert response.status_code == 422
    assert "no adapter yet" in response.text


# --- pick a provider, see its models, bind them ---------------------------------------


def test_selecting_a_provider_lists_the_models_it_actually_serves(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flow: add a provider, then choose from what it really has."""
    _stub_models(monkeypatch, ["openai/gpt-oss-20b", "openai/gpt-oss-120b"])
    identifier = client.post("/providers", json=_payload()).json()["id"]

    body = client.get(f"/providers/{identifier}/models").json()

    assert body["live"] is True
    assert body["models"] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert body["warnings"] == []


def test_a_provider_without_a_models_endpoint_falls_back_and_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fallback presented as a live answer is the thing to avoid."""

    async def unsupported(self: Any) -> list[str]:
        raise ProviderError("no /models here", retryable=False)

    monkeypatch.setattr(ChatCompletionsProvider, "list_models", unsupported, raising=True)
    created = client.post("/providers", json=_payload(manual_models=["typed-by-hand"]))
    identifier = created.json()["id"]

    body = client.get(f"/providers/{identifier}/models").json()

    assert body["live"] is False, "a fallback was presented as a live answer"
    assert body["models"] == ["typed-by-hand"]


def test_nothing_to_choose_from_is_a_502_rather_than_an_empty_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty picker looks like "this provider has no models", which is wrong."""

    async def unsupported(self: Any) -> list[str]:
        raise ProviderError("unreachable", retryable=True)

    monkeypatch.setattr(ChatCompletionsProvider, "list_models", unsupported, raising=True)
    identifier = client.post("/providers", json=_payload()).json()["id"]

    response = client.get(f"/providers/{identifier}/models")
    assert response.status_code == 502
    assert "nothing to choose from" in response.text


def test_binding_a_tier_to_a_real_model_sticks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_models(monkeypatch, ["cheap-model", "big-model"])
    identifier = client.post("/providers", json=_payload()).json()["id"]

    bound = client.put(
        f"/providers/{identifier}/tiers",
        json={"cheap": "cheap-model", "balanced": "big-model", "frontier": "big-model"},
    )

    assert bound.status_code == 200, bound.text
    assert bound.json()["tiers"] == {
        "cheap": "cheap-model",
        "balanced": "big-model",
        "frontier": "big-model",
    }


def test_binding_a_tier_to_a_model_the_provider_does_not_serve_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings time is when this costs nothing. Mid-investigation it is an outage."""
    _stub_models(monkeypatch, ["cheap-model"])
    identifier = client.post("/providers", json=_payload()).json()["id"]

    response = client.put(
        f"/providers/{identifier}/tiers", json={"cheap": "a-model-that-was-renamed"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["unknown"] == {"cheap": "a-model-that-was-renamed"}
    assert detail["available"] == ["cheap-model"], (
        "the refusal does not say what could be chosen instead"
    )


def test_a_tier_bound_to_a_deprecated_model_is_warned_about(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0004: an incident is the worst moment to discover the binding is stale.

    Bound while the model existed, then the vendor withdrew it - which is
    precisely what happened to `llama-3.1-8b-instant` on this project's first
    live Groq run.
    """
    _stub_models(monkeypatch, ["still-here"])
    identifier = client.post("/providers", json=_payload()).json()["id"]
    client.put(f"/providers/{identifier}/tiers", json={"cheap": "still-here"})

    _stub_models(monkeypatch, ["a-replacement"])
    body = client.get(f"/providers/{identifier}/models").json()

    assert body["stale_tier_bindings"] == {"cheap": "still-here"}
    assert body["warnings"], "a stale binding produced no warning"
    assert "no longer serves" in body["warnings"][0]


# --- the store's own edges ------------------------------------------------------------


@pytest.mark.asyncio
async def test_operations_on_a_provider_that_is_not_there_return_none(
    store: InMemoryProviderStore,
) -> None:
    """None rather than a raise: the router turns absence into a 404 once."""
    missing = uuid4()

    assert await store.get(missing) is None
    assert await store.update(missing, api_key="x") is None
    assert await store.reveal_key(missing) is None
    assert await store.delete(missing) is False


@pytest.mark.asyncio
async def test_revealing_a_key_that_was_never_set_is_none_not_empty_string(
    store: InMemoryProviderStore,
) -> None:
    """`""` would be sent as an Authorization header; None cannot be."""
    config = config_from_input(
        provider_id="local",
        display_name="Local",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="http://localhost:11434/v1",
        auth_mode=AuthMode.NONE,
    )
    stored = await store.create(config)

    assert stored.has_key is False
    assert await store.reveal_key(stored.id) is None


def test_a_database_row_becomes_a_provider_with_its_tiers_typed() -> None:
    """`row_to_stored` is the only place a stored tier string becomes a `Tier`.

    It lives outside the Postgres module because it takes a mapping and opens no
    connection - so it stays under the coverage floor rather than riding the
    exemption.
    """
    from core.store.providers import row_to_stored

    config = config_from_input(
        provider_id="groq",
        display_name="Groq",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="https://api.groq.com/openai/v1",
        auth_mode=AuthMode.BEARER,
    )
    stamp = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    identifier = uuid4()

    stored = row_to_stored(
        {
            "id": identifier,
            "config": config.model_dump_json(),
            "sealed_key": json.dumps(seal(SECRET, master=MASTER).as_dict()),
            "tiers": json.dumps({"cheap": "small", "frontier": "big"}),
            "created_at": stamp,
            "updated_at": stamp,
        }
    )

    assert stored.id == identifier
    assert stored.has_key is True, "a row with a sealed key reported none"
    assert stored.tiers == {Tier.CHEAP: "small", Tier.FRONTIER: "big"}
    assert SECRET not in json.dumps(stored.as_dict())


def test_a_row_with_no_key_and_no_tiers_is_read_without_guessing() -> None:
    """The two nullable columns, which is where a row adapter usually breaks."""
    from core.store.providers import row_to_stored

    config = config_from_input(
        provider_id="local",
        display_name="Local",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="http://localhost:11434/v1",
        auth_mode=AuthMode.NONE,
    )
    stamp = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

    stored = row_to_stored(
        {
            "id": uuid4(),
            "config": config.model_dump_json(),
            "sealed_key": None,
            "tiers": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
    )

    assert stored.has_key is False
    assert stored.tiers == {}


def test_a_sealed_record_survives_the_round_trip_through_storage() -> None:
    """Postgres stores the record as JSON, so this is the shape that matters."""
    sealed = seal(SECRET, master=MASTER)
    reloaded = Sealed.from_dict(json.loads(json.dumps(sealed.as_dict())))

    assert reloaded == sealed
    assert open_sealed(reloaded, master=MASTER) == SECRET


def test_a_well_formed_master_key_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    import core.cerberus.store.master_key as module

    raw = os.urandom(32)
    monkeypatch.setattr(module, "get_settings", lambda: _settings(base64.b64encode(raw).decode()))

    assert resolve() == raw


def test_binding_against_an_unreachable_provider_falls_back_to_the_manual_list(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And still refuses a model that list does not contain.

    Losing the check entirely because the provider is momentarily down would
    make an outage the moment a typo is easiest to introduce.
    """

    async def unreachable(self: Any) -> list[str]:
        raise ProviderError("down", retryable=True)

    monkeypatch.setattr(ChatCompletionsProvider, "list_models", unreachable, raising=True)
    created = client.post("/providers", json=_payload(manual_models=["written-down"]))
    identifier = created.json()["id"]

    assert client.put(f"/providers/{identifier}/tiers", json={"cheap": "typo"}).status_code == 422
    assert (
        client.put(f"/providers/{identifier}/tiers", json={"cheap": "written-down"}).status_code
        == 200
    )


# --- probing, which is what makes a declared capability resolvable ------------------


def _probing(monkeypatch: pytest.MonkeyPatch, reply: str = '{"ok": true}') -> None:
    """Answer the probe's completions without a socket."""

    async def complete(self: Any, **kwargs: Any) -> Any:
        from core.llm.provider import Completion

        return Completion(text=reply, model_id=str(kwargs.get("model_id", "m")))

    monkeypatch.setattr(ChatCompletionsProvider, "complete", complete, raising=True)


def test_probing_records_what_the_models_can_do(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop the provider CRUD started: add a provider, probe it, and an
    agent that declares JSON_MODE can finally resolve a model."""
    _stub_models(monkeypatch, ["m-1", "m-2"])
    _probing(monkeypatch)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    body = client.post(f"/providers/{identifier}/probe").json()

    assert body["reachable"] == ["m-1"]
    assert body["unreachable"] == []
    probed = body["probed"][0]
    assert "json_mode" in probed["present"]
    assert "tool_use" in probed["unprobed"], (
        "tool_use was reported as present or absent, but nothing can probe it - "
        "Provider.complete has nowhere to put a tool schema"
    )


def test_a_probe_reaches_the_matrix_an_agent_actually_reads(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring that matters. Without it, probing updates a settings page and
    changes nothing an agent can see - the model stays unresolvable while the
    UI shows a green tick."""
    from core.llm.capability_matrix import default as default_matrix

    _stub_models(monkeypatch, ["m-1"])
    _probing(monkeypatch)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    client.post(f"/providers/{identifier}/probe")

    assert Capability.JSON_MODE in default_matrix().capabilities_for("groq", "m-1")


def test_an_unreachable_model_is_reported_rather_than_raising(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that is down is an observation. Raising would lose the results
    for every model probed before it."""

    async def refuse(self: Any, **kwargs: Any) -> Any:
        raise ProviderError("401 invalid key", retryable=False)

    _stub_models(monkeypatch, ["m-1"])
    monkeypatch.setattr(ChatCompletionsProvider, "complete", refuse, raising=True)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    body = client.post(f"/providers/{identifier}/probe").json()

    assert body["unreachable"] == ["m-1"]
    assert "401" in body["probed"][0]["error"]


def test_probing_nothing_is_refused_rather_than_reported_as_success(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty probe run returning 200 reads as "everything checked out"."""
    _stub_models(monkeypatch, ["m-1"])
    identifier = client.post("/providers", json=_payload()).json()["id"]

    response = client.post(f"/providers/{identifier}/probe")

    assert response.status_code == 422
    assert "no models to probe" in response.text


def test_probing_does_not_default_to_every_model_a_provider_lists(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dozens of paid requests is not a sensible default for a button.

    The default is what this deployment actually uses - the bound tiers, or the
    manual list - not everything the vendor serves.
    """
    _stub_models(monkeypatch, [f"m-{index}" for index in range(30)])
    _probing(monkeypatch)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    body = client.post(f"/providers/{identifier}/probe").json()

    assert len(body["probed"]) == 1, (
        f"probed {len(body['probed'])} models; the default must be what is configured"
    )


def test_an_explicit_model_list_is_honoured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control. A default that ignored the argument would pass the test above."""
    _stub_models(monkeypatch, ["m-1", "m-2", "m-3"])
    _probing(monkeypatch)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    body = client.post(f"/providers/{identifier}/probe", json={"models": ["m-2", "m-3"]}).json()

    assert body["reachable"] == ["m-2", "m-3"]


def test_probing_never_returns_the_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_models(monkeypatch, ["m-1"])
    _probing(monkeypatch)
    identifier = client.post("/providers", json=_payload(manual_models=["m-1"])).json()["id"]

    text = client.post(f"/providers/{identifier}/probe").text

    assert SECRET not in text
    assert "gsk_" not in text
