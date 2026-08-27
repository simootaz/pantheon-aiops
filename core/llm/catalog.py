"""Configured providers: load, validate, enumerate.

Named catalog rather than registry on purpose - core/registry/ is the agent
registry, and two registry modules in one package tree invites import confusion
and mis-greps.

WHAT A CATALOGUE ENTRY CLAIMS
------------------------------
A `ModelDescriptor` says what a model *is observed to be*. This module builds
them from settings, which means the observation is "an operator configured
this", not "we probed it and it answered".

That distinction is carried rather than smoothed over: `last_probed_at` stays
`None` for a configured-but-unprobed model, and capabilities come from
`BASELINE_CAPABILITIES` rather than an optimistic guess. Probing is Phase 4.
Until then a model claiming `TOOL_USE` would be a claim nobody checked, and an
agent that declared `TOOL_USE` and silently got a model without it does not
fail - it produces confident nonsense.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import get_settings
from core.contracts.llm import Capability, ModelDescriptor, ProviderConfig, Tier
from core.llm.provider import BASELINE_CAPABILITIES, Provider


class NoSuchModel(LookupError):
    """The catalogue holds nothing under that id."""


@dataclass(frozen=True)
class Catalogue:
    """Every configured provider, the models they expose, and the tier map.

    `by_tier` is the normal resolution path and is kept explicit rather than
    derived from a naming convention - "the model with 32b in its name is the
    frontier one" is a rule that breaks the first time a provider renames
    something.
    """

    providers: dict[str, ProviderConfig]
    models: dict[str, ModelDescriptor]
    by_tier: dict[Tier, str]

    def descriptor(self, model_id: str) -> ModelDescriptor:
        try:
            return self.models[model_id]
        except KeyError as missing:
            raise NoSuchModel(
                f"no model {model_id!r} in the catalogue. Configured: {sorted(self.models)}"
            ) from missing

    def for_tier(self, tier: Tier) -> ModelDescriptor | None:
        """The model configured for a tier, or None when nothing is."""
        model_id = self.by_tier.get(tier)
        return self.models.get(model_id) if model_id else None


def from_settings() -> Catalogue:
    """Build the catalogue from `LLM_*`.

    One provider today, because settings describe one. The shape is a mapping so
    that a second provider is a configuration change rather than a refactor -
    which is the acceptance test ADR 0004 sets: swapping providers must require
    zero code changes across the agents.
    """
    llm = get_settings().delphi

    provider = ProviderConfig(
        id=llm.provider_id,
        display_name=llm.display_name,
        dialect=llm.dialect,
        base_url=llm.base,
        auth_mode=llm.auth_mode,
        secret_ref="LLM_API_KEY" if llm.api_key else None,
        manual_models=sorted(
            {llm.tier_cheap_model, llm.tier_balanced_model, llm.tier_frontier_model}
        ),
    )

    by_tier = {
        Tier.CHEAP: llm.tier_cheap_model,
        Tier.BALANCED: llm.tier_balanced_model,
        Tier.FRONTIER: llm.tier_frontier_model,
    }
    models = {model_id: _descriptor(provider.id, model_id) for model_id in provider.manual_models}
    return Catalogue(providers={provider.id: provider}, models=models, by_tier=by_tier)


def _descriptor(provider_id: str, model_id: str) -> ModelDescriptor:
    """A configured model, described honestly as unprobed.

    `context_window` is 0 rather than a guess. Zero fails a `min_context`
    requirement, which is the safe direction: an agent that needs 32k tokens and
    is handed an unknown window should be refused, not given one that might
    truncate its prompt silently.
    """
    return ModelDescriptor(
        provider_id=provider_id,
        model_id=model_id,
        context_window=0,
        capabilities=sorted(BASELINE_CAPABILITIES),
        median_latency_ms=None,
        last_probed_at=None,
    )


async def enumerate_models(provider: Provider, config: ProviderConfig) -> list[str]:
    """What the provider actually exposes, falling back to the manual list.

    The endpoint is asked first because a live answer beats a configured one,
    and the manual list is the fallback because plenty of gateways do not
    implement `/models` at all. A provider that answers with nothing is treated
    as not having answered - an empty catalogue is never the useful reading.
    """
    try:
        live = await provider.list_models()
    except Exception:
        return list(config.manual_models)
    return live or list(config.manual_models)


def satisfies(model: ModelDescriptor, *, required: list[Capability], min_context: int) -> bool:
    """Whether one model meets a declared requirement.

    Missing capability information counts as *not having* the capability. The
    alternative - treating unknown as acceptable - is precisely the silent
    downgrade ADR 0004 forbids, and it fails in the direction that produces
    plausible output rather than an error.
    """
    if min_context and model.context_window < min_context:
        return False
    return set(required) <= set(model.capabilities)
