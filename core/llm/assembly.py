"""Building a `Delphi` from configuration, so agents do not each invent one.

`catalog.from_settings()` already describes WHICH models exist. This is the other
half: the adapters that can actually call them, and the key each one needs.

WHY THIS IS NOT IN `gateway.py`
---------------------------------
`Delphi.__init__` takes its providers. That is deliberate - a test hands it a
recording fake, and a gateway that reached for configuration itself could not be
tested without one. This module is the *default* wiring, kept separate so the
injection point stays injectable.

WHAT IT REFUSES
-----------------
An unconfigured Delphi is not built with an empty provider map. Every `consult`
would then fail deep inside the fallback chain with "no adapter for its
provider", which reads as a broken catalogue rather than as missing
configuration - and the two are fixed in completely different places.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from core.config import get_settings
from core.contracts.llm import Dialect
from core.llm.catalog import from_settings as catalogue_from_settings
from core.llm.gateway import Delphi
from core.llm.provider import Provider
from core.llm.providers.chat_completions import ChatCompletionsProvider


class DelphiNotConfigured(RuntimeError):
    """No usable LLM provider is configured, so nothing can be consulted.

    A refusal rather than an empty gateway. The distinction matters at the point
    of failure: this says "set LLM_API_KEY", while an empty provider map says
    "no adapter for its provider" from inside a fallback chain three frames
    down, and a reader would go looking at the catalogue.
    """


def providers_from_settings() -> dict[str, Provider]:
    """One adapter per configured provider, keyed the way the catalogue keys it.

    Only `chat_completions` has an adapter today. A provider configured with any
    other dialect is refused here rather than skipped, because a skipped provider
    leaves a catalogue entry nothing can serve - which is exactly the state this
    module exists to prevent.
    """
    llm = get_settings().delphi

    if llm.dialect is not Dialect.CHAT_COMPLETIONS:
        raise DelphiNotConfigured(
            f"LLM_DIALECT is {llm.dialect.value!r}, and only "
            f"{Dialect.CHAT_COMPLETIONS.value!r} has an adapter. The others are "
            "ADR 0004 Phase 5."
        )

    key = llm.api_key.get_secret_value() if llm.api_key else None
    if not key and llm.auth_mode.value != "none":
        raise DelphiNotConfigured(
            f"LLM_AUTH_MODE is {llm.auth_mode.value!r} but LLM_API_KEY is empty, so "
            "no model can be called. Set it in the repository-root .env, or set "
            "LLM_AUTH_MODE=none for a local provider that wants no credential."
        )

    catalogue = catalogue_from_settings()
    config = catalogue.providers[llm.provider_id]
    return {llm.provider_id: ChatCompletionsProvider(config, api_key=key)}


def delphi_from_settings() -> Delphi:
    """The gateway an agent gets when nobody injected one."""
    return Delphi(providers=providers_from_settings(), catalogue=catalogue_from_settings())
