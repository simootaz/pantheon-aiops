"""The resolution cascade, which is where ADR 0004's central invariant lives.

> Agents never name a model. They declare `ModelRequirements`; Delphi resolves
> those to a concrete model at call time.

The acceptance test the ADR sets is that swapping providers in settings requires
zero code changes across all eleven agents. What that reduces to here: an agent
supplies requirements and nothing else, and every decision about which model
answers is made from the catalogue and the bindings.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import pytest

from core.contracts.llm import (
    AuthMode,
    Capability,
    Dialect,
    ModelDescriptor,
    ModelRequirements,
    ProviderConfig,
    ResolutionStep,
    Tier,
)
from core.llm.catalog import Catalogue, NoSuchModel, satisfies
from core.llm.resolver import Bindings, OverrideRejected, Unresolvable, resolve

PROVIDER = "test-provider"


def _model(
    model_id: str,
    *,
    context: int = 128_000,
    capabilities: list[Capability] | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        provider_id=PROVIDER,
        model_id=model_id,
        context_window=context,
        capabilities=capabilities if capabilities is not None else [Capability.STREAMING],
    )


def _catalogue(**models: ModelDescriptor) -> Catalogue:
    by_tier = {
        Tier.CHEAP: models.get("cheap", _model("cheap")).model_id,
        Tier.BALANCED: models.get("balanced", _model("balanced")).model_id,
        Tier.FRONTIER: models.get("frontier", _model("frontier")).model_id,
    }
    resolved = {name: models.get(name, _model(name)) for name in ("cheap", "balanced", "frontier")}
    return Catalogue(
        providers={
            PROVIDER: ProviderConfig(
                id=PROVIDER,
                display_name="Test",
                dialect=Dialect.CHAT_COMPLETIONS,
                base_url="http://localhost:11434/v1",
                auth_mode=AuthMode.NONE,
            )
        },
        models={model.model_id: model for model in resolved.values()},
        by_tier=by_tier,
    )


def _requirements(**kwargs: object) -> ModelRequirements:
    return ModelRequirements(**kwargs)  # type: ignore[arg-type]


# --- the cascade, rung by rung -----------------------------------------------


def test_the_tier_the_agent_declared_is_the_normal_path() -> None:
    resolution = resolve(
        _requirements(tier=Tier.FRONTIER), catalogue=_catalogue(), requested_by="hermes"
    )
    assert resolution.model.model_id == "frontier"
    assert resolution.record.matched_step is ResolutionStep.TIER_DEFAULT
    assert resolution.record.fallback_used is False


def test_a_per_agent_binding_beats_the_tier() -> None:
    """Standing policy: "Hermes always uses the frontier tier"."""
    resolution = resolve(
        _requirements(tier=Tier.CHEAP),
        catalogue=_catalogue(),
        requested_by="hermes",
        bindings=Bindings(per_agent={"hermes": "frontier"}),
    )
    assert resolution.model.model_id == "frontier"
    assert resolution.record.matched_step is ResolutionStep.AGENT_BINDING


def test_a_binding_for_another_agent_does_not_apply() -> None:
    resolution = resolve(
        _requirements(tier=Tier.CHEAP),
        catalogue=_catalogue(),
        requested_by="lethe",
        bindings=Bindings(per_agent={"hermes": "frontier"}),
    )
    assert resolution.model.model_id == "cheap"
    assert resolution.record.matched_step is ResolutionStep.TIER_DEFAULT


def test_a_task_override_beats_everything() -> None:
    """The narrowest, most deliberate signal wins."""
    resolution = resolve(
        _requirements(tier=Tier.CHEAP),
        catalogue=_catalogue(),
        requested_by="hermes",
        bindings=Bindings(task_override="frontier", per_agent={"hermes": "balanced"}),
    )
    assert resolution.model.model_id == "frontier"
    assert resolution.record.matched_step is ResolutionStep.TASK_OVERRIDE


def test_the_global_default_catches_a_tier_with_nothing_configured() -> None:
    """So a fresh install works before anything is configured."""
    catalogue = _catalogue()
    catalogue.by_tier.pop(Tier.FRONTIER)

    resolution = resolve(
        _requirements(tier=Tier.FRONTIER),
        catalogue=catalogue,
        requested_by="hermes",
        bindings=Bindings(global_default_tier=Tier.BALANCED),
    )
    assert resolution.model.model_id == "balanced"
    assert resolution.record.matched_step is ResolutionStep.GLOBAL_DEFAULT
    assert resolution.record.fallback_used is True, (
        "a run that fell back to the global default must say so, or nobody can "
        "tell a configured choice from a last resort"
    )


# --- a binding that does not fit is skipped, not used -------------------------


def test_a_binding_that_cannot_satisfy_the_requirements_is_skipped() -> None:
    """Skipped, not enforced. The requirement is the agent's, the binding is policy.

    Policy that overrode a declared capability would be a way for an operator to
    break an agent without touching its code.
    """
    catalogue = _catalogue(
        balanced=_model("balanced", capabilities=[Capability.STREAMING, Capability.TOOL_USE]),
        cheap=_model("cheap", capabilities=[Capability.STREAMING]),
    )

    resolution = resolve(
        _requirements(tier=Tier.BALANCED, capabilities=[Capability.TOOL_USE]),
        catalogue=catalogue,
        requested_by="hermes",
        bindings=Bindings(per_agent={"hermes": "cheap"}),
    )

    assert resolution.model.model_id == "balanced"
    assert resolution.record.matched_step is ResolutionStep.TIER_DEFAULT
    assert any("cheap" in reason for reason in resolution.record.rejected), (
        f"the skipped binding was not recorded: {resolution.record.rejected}"
    )


def test_the_record_says_what_was_rejected_and_why() -> None:
    """The question asked after a bad run is "why that one?", and the answer is
    usually in what was declined."""
    catalogue = _catalogue(
        frontier=_model("frontier", capabilities=[Capability.STREAMING]),
        balanced=_model("balanced", capabilities=[Capability.STREAMING, Capability.JSON_MODE]),
    )

    resolution = resolve(
        _requirements(tier=Tier.FRONTIER, capabilities=[Capability.JSON_MODE]),
        catalogue=catalogue,
        requested_by="clio",
        bindings=Bindings(global_default_tier=Tier.BALANCED),
    )

    assert resolution.model.model_id == "balanced"
    assert resolution.record.rejected, "nothing was recorded as rejected"
    assert any("frontier" in reason for reason in resolution.record.rejected)
    assert any("does not satisfy" in reason for reason in resolution.record.rejected)


# --- an override that cannot fit is an error -----------------------------------


def test_an_override_that_cannot_satisfy_the_requirements_is_an_error() -> None:
    """Not a downgrade. Otherwise an override becomes a way to quietly break an agent."""
    catalogue = _catalogue(cheap=_model("cheap", capabilities=[Capability.STREAMING]))

    with pytest.raises(OverrideRejected, match="does not satisfy"):
        resolve(
            _requirements(capabilities=[Capability.TOOL_USE]),
            catalogue=catalogue,
            requested_by="hermes",
            bindings=Bindings(task_override="cheap"),
        )


def test_an_override_naming_an_unknown_model_is_an_error() -> None:
    with pytest.raises(OverrideRejected, match="not in the catalogue"):
        resolve(
            _requirements(),
            catalogue=_catalogue(),
            requested_by="hermes",
            bindings=Bindings(task_override="a-model-nobody-configured"),
        )


def test_an_override_error_is_distinguishable_from_nothing_matching() -> None:
    """Different fixes: one means configure more models, the other means fix the pin.

    `OverrideRejected` subclasses `Unresolvable` so a caller that only cares
    "resolution failed" still catches it, while one that wants to explain the
    failure can tell them apart.
    """
    assert issubclass(OverrideRejected, Unresolvable)


# --- the hard stop --------------------------------------------------------------


def test_nothing_satisfying_the_requirements_is_a_hard_stop() -> None:
    """The central refusal. A model missing a declared capability does not fail -
    it produces confident nonsense, which is far more expensive to debug."""
    catalogue = _catalogue()

    with pytest.raises(Unresolvable) as raised:
        resolve(
            _requirements(capabilities=[Capability.VISION]),
            catalogue=catalogue,
            requested_by="aegis",
        )

    message = str(raised.value)
    assert "aegis" in message, "the refusal does not say who asked"
    assert "vision" in message, "the refusal does not say what was needed"
    assert "confident nonsense" in message, (
        "the refusal does not say why it is a stop rather than a downgrade"
    )


def test_an_empty_catalogue_is_a_deployment_problem_not_a_requirements_one() -> None:
    """Different fixes, so different messages.

    "Nothing satisfied your requirements" sends a reader to loosen them. The
    actual problem is that no model is configured, and no candidate was rejected
    because none existed.
    """
    empty = Catalogue(providers={}, models={}, by_tier={})
    with pytest.raises(Unresolvable, match="nothing was configured at all") as raised:
        resolve(_requirements(), catalogue=empty, requested_by="argus")
    assert "deployment problem" in str(raised.value)


def test_a_rejection_is_recorded_once_however_many_times_it_is_tried() -> None:
    """The agent's tier and the global default are usually the same tier.

    An undeduplicated list reports the identical candidate twice, which reads as
    two separate considerations and makes the record describe something that did
    not happen.
    """
    catalogue = _catalogue()
    catalogue.by_tier.pop(Tier.BALANCED)

    with pytest.raises(Unresolvable) as raised:
        resolve(
            _requirements(tier=Tier.BALANCED, capabilities=[Capability.VISION]),
            catalogue=catalogue,
            requested_by="aegis",
            bindings=Bindings(global_default_tier=Tier.BALANCED),
        )

    message = str(raised.value)
    assert message.count("tier balanced (no model configured)") == 1, message


def test_a_context_window_shorter_than_required_is_refused() -> None:
    """Unknown context is zero, and zero fails - the safe direction.

    An agent that needs 32k and is handed an unknown window should be refused,
    not given one that might truncate its prompt silently.
    """
    catalogue = _catalogue(
        cheap=_model("cheap", context=0),
        balanced=_model("balanced", context=0),
        frontier=_model("frontier", context=0),
    )
    with pytest.raises(Unresolvable):
        resolve(_requirements(min_context=32_000), catalogue=catalogue, requested_by="hermes")


# --- what the catalogue claims ---------------------------------------------------


def test_a_missing_capability_counts_as_absent_not_unknown() -> None:
    """Treating unknown as acceptable is the silent downgrade ADR 0004 forbids."""
    unprobed = _model("unprobed", capabilities=[])
    assert satisfies(unprobed, required=[], min_context=0) is True
    assert satisfies(unprobed, required=[Capability.TOOL_USE], min_context=0) is False


def test_the_catalogue_refuses_a_model_it_does_not_hold() -> None:
    with pytest.raises(NoSuchModel, match="not-configured"):
        _catalogue().descriptor("not-configured")


def test_a_tier_with_no_model_returns_none_rather_than_guessing() -> None:
    catalogue = _catalogue()
    catalogue.by_tier.pop(Tier.CHEAP)
    assert catalogue.for_tier(Tier.CHEAP) is None


def test_no_agent_ever_names_a_model() -> None:
    """ADR 0004's acceptance test, as far as a unit test can carry it.

    `resolve` takes requirements and a codename. There is no parameter through
    which an agent could pass a model id - the only way to name one is
    `Bindings`, which is operator policy rather than agent code.
    """
    import inspect

    parameters = set(inspect.signature(resolve).parameters)
    assert parameters == {"requirements", "catalogue", "requested_by", "bindings"}, parameters


# --- the catalogue as built from settings -----------------------------------


def test_the_catalogue_is_built_from_settings_not_from_code() -> None:
    """ADR 0004's acceptance test: swapping providers is a settings change.

    Whatever the tier models are configured to be, the catalogue holds those and
    the tier map points at them. Nothing here names a model.
    """
    from core.config import get_settings
    from core.llm.catalog import from_settings

    catalogue = from_settings()
    delphi = get_settings().delphi

    assert set(catalogue.providers) == {delphi.provider_id}
    assert catalogue.by_tier[Tier.CHEAP] == delphi.tier_cheap_model
    assert catalogue.by_tier[Tier.BALANCED] == delphi.tier_balanced_model
    assert catalogue.by_tier[Tier.FRONTIER] == delphi.tier_frontier_model
    for tier in Tier:
        assert catalogue.for_tier(tier) is not None, f"{tier.value} resolves to nothing"


def test_a_configured_model_is_described_as_unprobed() -> None:
    """Configured is not observed, and the descriptor must not blur them.

    `context_window` is 0 and `last_probed_at` is None until something probes.
    Zero fails a `min_context` requirement, which is the safe direction: an
    agent needing 32k should be refused rather than handed a window that might
    truncate its prompt silently.
    """
    from core.llm.catalog import from_settings

    for model in from_settings().models.values():
        assert model.last_probed_at is None, "a model was marked probed without a probe"
        assert model.context_window == 0, (
            "an unprobed model claims a context window nobody measured"
        )
        assert Capability.TOOL_USE not in model.capabilities, (
            "an unprobed model claims TOOL_USE; an agent that declared it would "
            "receive a model without it and produce confident nonsense"
        )


@pytest.mark.asyncio
async def test_enumeration_prefers_a_live_answer() -> None:
    from core.llm.catalog import enumerate_models
    from core.llm.provider import RecordingProvider

    config = _catalogue().providers[PROVIDER].model_copy(update={"manual_models": ["configured"]})
    provider = RecordingProvider(models=["live-a", "live-b"])

    assert await enumerate_models(provider, config) == ["live-a", "live-b"]


@pytest.mark.asyncio
async def test_a_provider_answering_with_nothing_falls_back_to_the_manual_list() -> None:
    """An empty catalogue is never the useful reading.

    Plenty of gateways do not implement `/models` and answer with an empty list
    rather than an error.
    """
    from core.llm.catalog import enumerate_models
    from core.llm.provider import RecordingProvider

    config = _catalogue().providers[PROVIDER].model_copy(update={"manual_models": ["configured"]})
    assert await enumerate_models(RecordingProvider(models=[]), config) == ["configured"]


@pytest.mark.asyncio
async def test_a_provider_that_raises_falls_back_rather_than_failing_the_run() -> None:
    from core.llm.catalog import enumerate_models
    from core.llm.provider import ProviderError, RecordingProvider

    config = _catalogue().providers[PROVIDER].model_copy(update={"manual_models": ["configured"]})
    provider = RecordingProvider(models=[], error=ProviderError("down", retryable=True))

    class _Failing(RecordingProvider):
        async def list_models(self) -> list[str]:
            raise ProviderError("no /models endpoint")

    assert await enumerate_models(_Failing(), config) == ["configured"]
    assert provider.provider_id == "recording"


# --- what a completion carries -----------------------------------------------


@pytest.mark.asyncio
async def test_a_completion_carries_the_tokens_rather_than_inviting_a_recount() -> None:
    """A caller that re-tokenises gets a different number from the provider's own,
    and the two then disagree in the audit trail."""
    from core.llm.provider import RecordingProvider

    provider = RecordingProvider(reply="two words")
    completion = await provider.complete(model_id="m", prompt="one two three")

    assert completion.model_id == "m"
    assert completion.prompt_tokens == 3
    assert completion.completion_tokens == 2
    assert completion.total_tokens == 5
    assert completion.cost is None, "an unreported cost must stay None; zero would render as free"


@pytest.mark.asyncio
async def test_a_provider_error_says_whether_retrying_could_help() -> None:
    """Retrying a 400 forever is how a budget disappears."""
    from core.llm.provider import ProviderError, RecordingProvider

    provider = RecordingProvider(error=ProviderError("rate limited", retryable=True))
    with pytest.raises(ProviderError) as raised:
        await provider.complete(model_id="m", prompt="hello")

    assert raised.value.retryable is True
    assert provider.calls[0]["model_id"] == "m", "the call was not recorded"
