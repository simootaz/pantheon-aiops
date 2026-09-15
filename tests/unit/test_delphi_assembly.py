"""Building a Delphi from settings, and refusing to build a useless one.

The refusals are what this module is for. An empty gateway fails deep inside the
fallback chain with "no adapter for its provider", which reads as a broken
catalogue - and a catalogue and a missing key are fixed in completely different
places.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

import core.llm.assembly as assembly
from core.contracts.llm import AuthMode, Dialect
from core.llm.assembly import DelphiNotConfigured, delphi_from_settings, providers_from_settings
from core.llm.providers.chat_completions import ChatCompletionsProvider


class _Delphi:
    """The `LLM_*` group, as much of it as this module reads."""

    def __init__(
        self,
        *,
        dialect: Dialect = Dialect.CHAT_COMPLETIONS,
        auth_mode: AuthMode = AuthMode.BEARER,
        api_key: str | None = "a-key",
    ) -> None:
        self.provider_id = "groq"
        self.display_name = "Groq"
        self.dialect = dialect
        self.base = "https://api.groq.com/openai/v1"
        self.auth_mode = auth_mode
        self.api_key = SecretStr(api_key) if api_key is not None else None
        self.tier_cheap_model = "small"
        self.tier_balanced_model = "medium"
        self.tier_frontier_model = "large"


def _settings(monkeypatch: pytest.MonkeyPatch, delphi: _Delphi) -> None:
    class _Settings:
        pass

    holder = _Settings()
    holder.delphi = delphi  # type: ignore[attr-defined]
    monkeypatch.setattr(assembly, "get_settings", lambda: holder)

    import core.llm.catalog as catalog

    monkeypatch.setattr(catalog, "get_settings", lambda: holder)


def test_a_configured_provider_becomes_an_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, _Delphi())

    providers = providers_from_settings()

    assert set(providers) == {"groq"}, "the adapter is not keyed the way the catalogue keys it"
    assert isinstance(providers["groq"], ChatCompletionsProvider)


def test_a_missing_key_refuses_and_says_where_to_put_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not an empty gateway. `consult` would then fail three frames down with a
    message about adapters, and a reader would go looking at the catalogue."""
    _settings(monkeypatch, _Delphi(api_key=None))

    with pytest.raises(DelphiNotConfigured, match="LLM_API_KEY is empty"):
        providers_from_settings()


def test_a_local_provider_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control. A refusal that fired on every configuration would make the
    test above meaningless."""
    _settings(monkeypatch, _Delphi(auth_mode=AuthMode.NONE, api_key=None))

    assert set(providers_from_settings()) == {"groq"}


@pytest.mark.parametrize("dialect", [d for d in Dialect if d is not Dialect.CHAT_COMPLETIONS])
def test_a_dialect_with_no_adapter_is_refused_rather_than_skipped(
    dialect: Dialect, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skipping would leave a catalogue entry nothing can serve, which is the
    exact state this module exists to prevent."""
    _settings(monkeypatch, _Delphi(dialect=dialect))

    with pytest.raises(DelphiNotConfigured, match="has an adapter"):
        providers_from_settings()


def test_the_gateway_is_built_with_the_same_catalogue_its_providers_came_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two catalogues would let the resolver name a model no adapter serves."""
    _settings(monkeypatch, _Delphi())

    delphi = delphi_from_settings()

    assert set(delphi._providers) == set(delphi._catalogue.providers)


def test_the_key_is_read_through_the_secret_and_never_defaulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty string is not a key. Sending `Authorization: Bearer ` produces a
    401 that reads as a WRONG key rather than a missing one - which is exactly
    how a stray space in this project's own key cost a diagnosis."""
    _settings(monkeypatch, _Delphi(api_key=""))

    with pytest.raises(DelphiNotConfigured):
        providers_from_settings()


def test_nothing_here_logs_or_returns_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider holds it; nothing else may hand it back."""
    _settings(monkeypatch, _Delphi(api_key="gsk_secret_value"))

    providers: dict[str, Any] = dict(providers_from_settings())

    assert "gsk_secret_value" not in repr(providers), "the key is in the adapter's repr"
