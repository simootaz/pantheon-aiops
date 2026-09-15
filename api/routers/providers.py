"""LLM provider settings: add a provider, give it a key, pick its models.

The flow this exists for:

1. `POST /providers` - add any provider that speaks a dialect we implement,
   with its key. The key is sealed on the way in and never comes back out.
2. `GET /providers/{id}/models` - ask the provider what it actually serves.
   Live, not configured: a model list typed by hand goes stale the first time a
   vendor deprecates something, and the failure appears mid-investigation.
3. `PUT /providers/{id}/tiers` - bind those models to CHEAP, BALANCED and
   FRONTIER. Agents ask for a tier and never a model, so this is the only place
   a model id is ever chosen by a human.

WHY THE KEY NEVER COMES BACK
------------------------------
Not even masked. A masked key in a response body is still a key in a log, a
browser cache and a screenshot, and "we only showed the last four" is how the
first four leak too. `has_key` is a boolean; if someone needs to change it they
send a new one.

WHAT IS VALIDATED AT SETTINGS TIME, NOT MID-INVESTIGATION
-----------------------------------------------------------
ADR 0004: *"an incident is the worst possible moment to discover that the bound
model cannot call tools."* `GET /providers/{id}/models` reports which tiers are
bound to models the provider no longer lists, because that is the check that
would otherwise fail at 03:00.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.contracts.llm import AuthMode, Dialect, ProviderConfig, Tier
from core.llm.capability_matrix import default as default_matrix
from core.llm.probe import probe_into
from core.llm.provider import ProviderError
from core.llm.providers.chat_completions import ChatCompletionsProvider
from core.store.providers import ProviderStore, StoredProvider, config_from_input

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderInput(BaseModel):
    """What a settings form supplies when adding or editing a provider."""

    provider_id: str = Field(description="Stable identifier, e.g. 'groq'.")
    display_name: str
    dialect: Dialect = Dialect.CHAT_COMPLETIONS
    base_url: str = Field(
        description=(
            "Root of the provider's API, up to and including the version segment. "
            "Supplied by whoever adds the provider - deliberately not a constant "
            "here, since the whole point is that any provider can be added."
        )
    )
    auth_mode: AuthMode = AuthMode.BEARER
    enabled: bool = True
    manual_models: list[str] = Field(
        default_factory=list,
        description="Used only when the provider serves no /models endpoint.",
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "Sealed on arrival and never returned. Omit on an edit to keep the "
            "existing key; send an empty string to remove it."
        ),
    )


class TierBinding(BaseModel):
    """Which model backs each tier. Agents ask for a tier, never a model."""

    cheap: str | None = None
    balanced: str | None = None
    frontier: str | None = None

    def as_tiers(self) -> dict[Tier, str]:
        chosen = {
            Tier.CHEAP: self.cheap,
            Tier.BALANCED: self.balanced,
            Tier.FRONTIER: self.frontier,
        }
        return {tier: model for tier, model in chosen.items() if model}


def get_provider_store(request: Request) -> ProviderStore:
    store: ProviderStore | None = getattr(request.app.state, "provider_store", None)
    if store is None:  # pragma: no cover - the app factory always sets one
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="provider store is not configured",
        )
    return store


@router.get("", summary="Every configured provider")
async def list_providers(
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> list[dict[str, object]]:
    """No keys in the response, by construction - see the module docstring."""
    return [provider.as_dict() for provider in await store.list()]


@router.post("", status_code=status.HTTP_201_CREATED, summary="Add a provider")
async def create_provider(
    payload: ProviderInput,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> dict[str, object]:
    """Add any provider speaking a dialect we implement.

    The dialect is checked here rather than at first use: accepting a provider
    whose wire format has no adapter produces a record that looks configured and
    fails only when an agent needs it.
    """
    _refuse_unimplemented_dialect(payload.dialect)
    if payload.auth_mode is not AuthMode.NONE and not payload.api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"auth_mode={payload.auth_mode.value} needs an api_key. Use "
                "auth_mode=none for a local provider that wants no credential."
            ),
        )

    stored = await store.create(_config(payload), api_key=payload.api_key)
    return stored.as_dict()


@router.get("/{provider_id}", summary="One provider")
async def get_provider(
    provider_id: UUID,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> dict[str, object]:
    return (await _require(store, provider_id)).as_dict()


@router.put("/{provider_id}", summary="Edit a provider")
async def update_provider(
    provider_id: UUID,
    payload: ProviderInput,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> dict[str, object]:
    """Omitting `api_key` keeps the stored one; sending `""` removes it."""
    _refuse_unimplemented_dialect(payload.dialect)
    await _require(store, provider_id)
    updated = await store.update(provider_id, config=_config(payload), api_key=payload.api_key)
    if updated is None:  # pragma: no cover - _require already proved it exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider vanished")
    return updated.as_dict()


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove one")
async def delete_provider(
    provider_id: UUID,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> None:
    if not await store.delete(provider_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider_id}"
        )


@router.get("/{provider_id}/models", summary="What this provider actually serves")
async def list_models(
    provider_id: UUID,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> dict[str, object]:
    """Asked of the provider, not read from configuration.

    A hand-typed list goes stale the first time a vendor deprecates a model, and
    the way you find out is an investigation failing. Falls back to
    `manual_models` when the provider serves no `/models`, and says which
    happened so nobody mistakes a fallback for a live answer.
    """
    stored = await _require(store, provider_id)
    key = await store.reveal_key(provider_id)
    provider = ChatCompletionsProvider(stored.config, api_key=key)

    live = True
    try:
        models = await provider.list_models()
    except ProviderError as unreachable:
        live = False
        models = list(stored.config.manual_models)
        if not models:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    f"{stored.config.id} could not be asked for its models "
                    f"({unreachable}), and no manual list is configured, so there "
                    "is nothing to choose from."
                ),
            ) from unreachable

    bound = stored.tiers
    stale = {tier.value: model for tier, model in bound.items() if model not in models}
    return {
        "provider_id": stored.config.id,
        "live": live,
        "models": sorted(models),
        "tiers": {tier.value: model for tier, model in bound.items()},
        # Surfaced here because settings time is the only moment this is cheap
        # to fix. Mid-investigation it is an outage.
        "stale_tier_bindings": stale,
        "warnings": [
            f"the {tier} tier is bound to {model!r}, which this provider no longer serves"
            for tier, model in stale.items()
        ],
    }


@router.post("/{provider_id}/probe", summary="Ask this provider's models what they can do")
async def probe_provider(
    provider_id: UUID,
    store: Annotated[ProviderStore, Depends(get_provider_store)],
    models: Annotated[list[str] | None, Body(embed=True)] = None,
) -> dict[str, object]:
    """Run the capability probes and record what was observed.

    ON DEMAND, NEVER ON A TIMER
    -----------------------------
    Every probe is a real request that costs real money, charged to whoever
    pressed the button. Nothing here runs during an investigation, and nothing
    schedules it.

    WHY THIS ENDPOINT MATTERS MORE THAN IT LOOKS
    -----------------------------------------------
    Capabilities are OBSERVED, never declared - ADR 0004. Until something probes,
    no model is known to do anything beyond the baseline, and an agent that
    declares a capability hard-stops on every run. Hermes spent days in exactly
    that state: registered, reachable, and unresolvable, because nothing had
    ever asked a model whether it could return JSON.

    Results go into the process-wide matrix, which is what
    `core/llm/assembly.py` builds an agent's catalogue from. Probing here is
    therefore what makes a model resolvable there - see
    `core/llm/capability_matrix.default()` for what "process-wide" costs.
    """
    stored = await _require(store, provider_id)
    key = await store.reveal_key(provider_id)
    provider = ChatCompletionsProvider(stored.config, api_key=key)

    targets = (
        models if models else sorted(stored.tiers.values()) or list(stored.config.manual_models)
    )
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "no models to probe. Bind a tier or configure manual_models, or pass "
                "`models` - probing every model a provider lists can be dozens of paid "
                "requests, so it is not the default."
            ),
        )

    results = await probe_into(default_matrix(), provider, targets)
    return {
        "provider_id": stored.config.id,
        "probed": [result.as_dict() for result in results],
        # Separated so a caller can see at a glance whether anything is now
        # usable. A response that only listed results would need reading.
        "reachable": sorted(r.model_id for r in results if r.reachable),
        "unreachable": sorted(r.model_id for r in results if not r.reachable),
    }


@router.put("/{provider_id}/tiers", summary="Bind models to tiers")
async def set_tiers(
    provider_id: UUID,
    binding: Annotated[TierBinding, Body()],
    store: Annotated[ProviderStore, Depends(get_provider_store)],
) -> dict[str, object]:
    """The only place a human names a model.

    Bindings are checked against what the provider serves, because a tier
    pointing at a model that does not exist is a run that fails at dispatch -
    and this is the moment when fixing it costs nothing.
    """
    stored = await _require(store, provider_id)
    tiers = binding.as_tiers()

    key = await store.reveal_key(provider_id)
    try:
        available = set(await ChatCompletionsProvider(stored.config, api_key=key).list_models())
    except ProviderError:
        available = set(stored.config.manual_models)

    unknown = {tier.value: model for tier, model in tiers.items() if model not in available}
    if unknown and available:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "one or more tiers name a model this provider does not serve",
                "unknown": unknown,
                "available": sorted(available),
            },
        )

    updated = await store.update(provider_id, tiers=tiers)
    if updated is None:  # pragma: no cover - _require already proved it exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="provider vanished")
    return updated.as_dict()


def _config(payload: ProviderInput) -> ProviderConfig:
    return config_from_input(
        provider_id=payload.provider_id,
        display_name=payload.display_name,
        dialect=payload.dialect,
        base_url=payload.base_url,
        auth_mode=payload.auth_mode,
        manual_models=payload.manual_models,
        enabled=payload.enabled,
    )


def _refuse_unimplemented_dialect(dialect: Dialect) -> None:
    """Only `chat_completions` has an adapter today.

    Refused at the door rather than at first use, so a provider that cannot work
    never becomes a configured record someone trusts.
    """
    if dialect is not Dialect.CHAT_COMPLETIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"dialect {dialect.value!r} has no adapter yet - only "
                f"{Dialect.CHAT_COMPLETIONS.value} is implemented. The others are "
                "ADR 0004 Phase 5. A provider stored now would look configured and "
                "fail when an agent needed it."
            ),
        )


async def _require(store: ProviderStore, provider_id: UUID) -> StoredProvider:
    stored = await store.get(provider_id)
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no provider {provider_id}"
        )
    return stored
