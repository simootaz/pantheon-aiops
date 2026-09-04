"""Probing, the matrix, and the bug that made Hermes permanently unresolvable.

Hermes declares `JSON_MODE`. Nothing had ever probed, so no model listed it, so
the resolver hard-stopped on every run. Every unit test passed because they all
injected a scripted gateway and never reached the resolver - the seam hid it.

The guard at the bottom is the one that would have caught it.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.config import get_settings
from core.contracts.llm import Capability, ModelRequirements
from core.llm.capability_matrix import STALE_AFTER, CapabilityMatrix, Probed
from core.llm.catalog import Catalogue, from_settings
from core.llm.probe import PROBEABLE, probe_into, probe_model
from core.llm.provider import BASELINE_CAPABILITIES, ProviderError, RecordingProvider
from core.llm.resolver import Unresolvable, resolve

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _Ticker:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


#: The provider the catalogue is actually built from. Read rather than written
#: out, because `from_settings` looks probe results up by `(provider_id,
#: model_id)` and a literal here only matches when the developer's own .env
#: happens to name the same provider.
#:
#: It did. `LLM_PROVIDER_ID=groq` locally, `local-ollama` by default, so
#: `test_probing_is_what_makes_a_json_mode_agent_resolvable` passed on a laptop
#: and failed in CI - the probe recorded under one key and the catalogue read
#: another, and the resolver reported the model as unprobed. An
#: environment-dependent test that reports a real defect only somewhere else.
CONFIGURED_PROVIDER = get_settings().delphi.provider_id


def _provider(reply: str = '{"ok": true}', **kwargs: object) -> RecordingProvider:
    provider = RecordingProvider(reply=reply, **kwargs)  # type: ignore[arg-type]
    provider.provider_id = CONFIGURED_PROVIDER
    return provider


# --- three states, not two ---------------------------------------------------------


def test_a_capability_nobody_probed_is_not_the_same_as_one_that_is_absent() -> None:
    """The distinction the whole file rests on.

    A list of capabilities can say *has* and *does not have*. It cannot say
    *not checked*, and conflating the last two is what hard-stopped Hermes on a
    capability nobody had looked for.
    """
    probed = Probed(
        provider_id="groq",
        model_id="m",
        at=NOW,
        present=frozenset({Capability.JSON_MODE}),
        absent=frozenset({Capability.VISION}),
    )

    assert Capability.JSON_MODE in probed.present
    assert Capability.VISION in probed.absent
    assert Capability.TOOL_USE in probed.unprobed(), (
        "a capability in neither set must report as unprobed, not as absent"
    )


def test_an_unprobed_model_reports_every_capability_as_unknown() -> None:
    """Not as absent. A caller can then say "not known to support X" rather than
    "does not support X" - different sentences to put in front of an operator."""
    matrix = CapabilityMatrix(clock=_Ticker())

    assert matrix.capabilities_for("groq", "m") == frozenset()
    assert matrix.unprobed_for("groq", "m") == frozenset(Capability)


def test_a_stale_observation_stops_counting() -> None:
    """A provider can change what sits behind a stable model id. An entry old
    enough that nobody would defend it must not keep authorising resolutions."""
    clock = _Ticker()
    matrix = CapabilityMatrix(clock=clock)
    matrix.record(
        Probed(provider_id="groq", model_id="m", at=NOW, present=frozenset({Capability.JSON_MODE}))
    )

    assert matrix.capabilities_for("groq", "m") == frozenset({Capability.JSON_MODE})

    clock.now = NOW + STALE_AFTER + timedelta(seconds=1)

    assert matrix.capabilities_for("groq", "m") == frozenset()
    assert matrix.get("groq", "m") is not None, (
        "the stale entry was deleted; a UI showing the value and its age needs it"
    )
    assert [entry.model_id for entry in matrix.stale()] == ["m"]


def test_staleness_is_answered_on_read() -> None:
    """Like the approval gate's expiry, and for the same reason: a sweep makes
    the answer depend on whether the sweep ran."""
    clock = _Ticker()
    matrix = CapabilityMatrix(clock=clock)
    matrix.record(
        Probed(provider_id="groq", model_id="m", at=NOW, present=frozenset({Capability.JSON_MODE}))
    )

    clock.now = NOW + STALE_AFTER
    assert matrix.fresh("groq", "m") is None

    clock.now = NOW
    assert matrix.fresh("groq", "m") is not None, "freshness did not follow the clock back"


# --- what a probe actually establishes ------------------------------------------------


@pytest.mark.asyncio
async def test_a_model_that_returns_json_is_recorded_as_having_json_mode() -> None:
    probed = await probe_model(_provider('{"ok": true}'), "m")

    assert Capability.JSON_MODE in probed.present
    assert probed.reachable
    assert probed.median_latency_ms is not None


@pytest.mark.asyncio
async def test_a_model_that_returns_prose_is_recorded_as_lacking_it() -> None:
    """Parsed, not pattern-matched. A model emitting ```json fences around valid
    JSON has not returned JSON, and the caller doing `json.loads` gets an
    exception - so the probe measures what the caller will actually do."""
    probed = await probe_model(_provider('```json\n{"ok": true}\n```'), "m")

    assert Capability.JSON_MODE in probed.absent
    assert Capability.JSON_MODE not in probed.present


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_an_observation_not_an_exception() -> None:
    """ "We tried and it refused" and "nobody has looked" are different, and only
    the first is worth retrying soon."""
    probed = await probe_model(_provider(error=ProviderError("401", retryable=False)), "m")

    assert not probed.reachable
    assert "unreachable" in probed.error
    assert probed.present == frozenset(), "an unreachable model was credited with capabilities"


@pytest.mark.asyncio
async def test_an_empty_answer_is_reported_as_a_probe_failure_not_a_missing_capability() -> None:
    """A reasoning model given too small a ceiling spends it thinking and
    returns nothing - which this project has already been bitten by. That is a
    fact about the request, not about what the model can do."""
    probed = await probe_model(_provider(""), "m")

    assert "empty text" in probed.error
    assert Capability.JSON_MODE not in probed.absent, (
        "an empty answer was recorded as the model lacking JSON_MODE"
    )


@pytest.mark.asyncio
async def test_baseline_capabilities_survive_probing() -> None:
    """STREAMING is assumed for chat_completions and nothing probes it. Dropping
    it on probe would make probing a model REMOVE a capability."""
    probed = await probe_model(_provider(), "m")

    assert probed.present >= BASELINE_CAPABILITIES


@pytest.mark.asyncio
async def test_a_context_window_is_never_guessed() -> None:
    """Nothing measures one. Zero fails a `min_context` requirement, which is
    the safe direction - a guess would satisfy it and truncate silently."""
    probed = await probe_model(_provider(), "m")

    assert probed.context_window == 0


@pytest.mark.asyncio
async def test_probing_several_models_records_the_failures_too() -> None:
    """A run that dropped its failures would leave the failed models looking
    unprobed, and they would be re-probed identically forever."""
    matrix = CapabilityMatrix(clock=_Ticker())
    provider = _provider(error=ProviderError("down", retryable=True))

    results = await probe_into(matrix, provider, ["a", "b"])

    assert len(results) == 2
    assert len(matrix) == 2
    assert all(not entry.reachable for entry in results)


# --- the bug this file exists for -------------------------------------------------------


@pytest.mark.asyncio
async def test_probing_is_what_makes_a_json_mode_agent_resolvable() -> None:
    """Hermes declares JSON_MODE. Before anything probed, no model listed it and
    every Hermes run hard-stopped with `Unresolvable` - which read as a broken
    resolver and was really a system with no observations in it.
    """
    requirements = ModelRequirements(capabilities=[Capability.JSON_MODE])

    with pytest.raises(Unresolvable):
        resolve(requirements, catalogue=from_settings(), requested_by="hermes")

    matrix = CapabilityMatrix(clock=_Ticker())
    catalogue = from_settings()
    await probe_into(matrix, _provider(), list(catalogue.models))

    # The probe must have recorded under the key the catalogue reads back. A
    # mismatch leaves every model looking unprobed and the resolver reporting
    # a broken catalogue - which is the shape of the original bug, arrived at
    # from the other side.
    assert all(matrix.fresh(CONFIGURED_PROVIDER, model_id) for model_id in catalogue.models), (
        "probe results were recorded under a provider id the catalogue does not read"
    )

    resolution = resolve(requirements, catalogue=from_settings(matrix), requested_by="hermes")
    assert Capability.JSON_MODE in resolution.model.capabilities


@pytest.mark.asyncio
async def test_a_probe_that_found_nothing_does_not_make_a_model_resolvable() -> None:
    """The control. If probing granted capabilities regardless of the answer,
    the test above would pass for the wrong reason."""
    requirements = ModelRequirements(capabilities=[Capability.JSON_MODE])
    matrix = CapabilityMatrix(clock=_Ticker())
    catalogue = from_settings()
    await probe_into(matrix, _provider("not json at all"), list(catalogue.models))

    with pytest.raises(Unresolvable):
        resolve(requirements, catalogue=from_settings(matrix), requested_by="hermes")


def test_an_unprobed_catalogue_describes_itself_as_unprobed() -> None:
    """`last_probed_at` is None, so a settings UI cannot show a green tick over
    a model nobody has ever called."""
    for descriptor in from_settings().models.values():
        assert descriptor.last_probed_at is None
        assert set(descriptor.capabilities) == set(BASELINE_CAPABILITIES)


# --- the guard that would have caught it ---------------------------------------------------


def test_every_capability_an_implemented_agent_requires_can_be_probed() -> None:
    """A requirement nothing can ever establish is worse than a missing probe.

    It presents as a resolver bug: the agent is registered, reachable, and
    hard-stops on every run with a message about capabilities. Hermes spent days
    in exactly that state.

    `PROBEABLE` is what `core/llm/probe.py` can actually measure. TOOL_USE and
    VISION are outside it because `Provider.complete` has nowhere to put a tool
    schema or an image - so an agent declaring either would be undispatchable
    until the adapter grows a parameter, and that must fail here rather than at
    three in the morning.
    """
    from importlib import import_module

    from core.orchestrator import planner

    agents = {
        "argus": "agents.anomaly.agent",
        "aegis": "agents.manifest_review.agent",
        "hephaestus": "agents.ci_triage.agent",
        "lethe": "agents.log_clustering.agent",
        "hermes": "agents.nl_query.agent",
    }
    for codename in sorted(planner.IMPLEMENTED.values()):
        assert codename in agents, (
            f"{codename} is dispatchable and this check does not know where its "
            "module lives. Add it, or its requirements are unchecked."
        )
        module = import_module(agents[codename])
        declared = {
            name: value
            for name, value in vars(module).items()
            if isinstance(value, ModelRequirements)
        }
        for name, requirements in sorted(declared.items()):
            impossible = set(requirements.capabilities) - PROBEABLE - set(BASELINE_CAPABILITIES)
            assert not impossible, (
                f"{codename}.{name} requires {sorted(c.value for c in impossible)}, which "
                f"nothing can probe. PROBEABLE is {sorted(c.value for c in PROBEABLE)} and "
                f"baseline is {sorted(c.value for c in BASELINE_CAPABILITIES)}. The agent "
                "would hard-stop on every run and it would read as a resolver bug."
            )


def test_the_probeable_set_is_not_empty() -> None:
    """The guard above passes vacuously if nothing is probeable."""
    assert PROBEABLE, "no capability can be probed, so the guard above proves nothing"


# --- the wiring, without which probing changes nothing an agent can see -------------


@pytest.mark.asyncio
async def test_a_probe_reaches_the_gateway_an_agent_builds_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The link that makes probing worth anything.

    Agents build their gateway lazily through `delphi_from_settings()`, and
    there is no path from the API's app state into an agent's gateway. Without
    the process-wide matrix, a probe recorded by the API would update a settings
    page and leave the agent exactly as unresolvable as before - with a green
    tick over it.

    A plant removing that fallback passed every other test in this repository.
    """
    from core.contracts.llm import ModelRequirements
    from core.llm import assembly
    from core.llm.capability_matrix import default as default_matrix
    from core.llm.resolver import resolve

    monkeypatch.setattr(assembly, "providers_from_settings", lambda: {})

    from core.contracts.llm import Tier

    matrix = default_matrix()
    catalogue = from_settings()
    # The model bound to the tier the requirements default to. Seeding any other
    # would leave the resolver looking at an unprobed one and the test would
    # fail for a reason unrelated to the wiring it is about.
    model_id = catalogue.by_tier[Tier.BALANCED]
    provider_id = catalogue.models[model_id].provider_id
    monkeypatch.setitem(
        matrix._entries,
        (provider_id, model_id),
        Probed(
            provider_id=provider_id,
            model_id=model_id,
            at=datetime.now(tz=UTC),
            present=frozenset({Capability.JSON_MODE}),
        ),
    )

    delphi = assembly.delphi_from_settings()
    resolution = resolve(
        ModelRequirements(capabilities=[Capability.JSON_MODE]),
        catalogue=delphi._catalogue,
        requested_by="hermes",
    )

    assert Capability.JSON_MODE in resolution.model.capabilities, (
        "the gateway an agent builds does not see probed capabilities, so probing "
        "changes nothing it can act on"
    )


# --- the fallback chain never widens the requirements --------------------------------


def _catalogue_with(probed_models: dict[str, set[Capability]]) -> Catalogue:
    """A catalogue where the named models have the named capabilities observed."""
    matrix = CapabilityMatrix(clock=_Ticker())
    base = from_settings()
    for model_id, capabilities in probed_models.items():
        matrix.record(
            Probed(
                provider_id=base.models[model_id].provider_id,
                model_id=model_id,
                at=NOW,
                present=frozenset(capabilities),
            )
        )
    return from_settings(matrix)


def test_the_chain_only_offers_models_that_satisfy_the_same_requirements() -> None:
    """The rule an optimisation would quietly break.

    A chain that dropped a declared capability when the first choice was
    unreachable would produce its worst output exactly when the system is
    already struggling - and nothing in the result would say so. The agent asked
    for JSON_MODE, got prose, and reports a parse error about a model it never
    chose.
    """
    from core.contracts.llm import ModelRequirements, Tier
    from core.llm.fallback import chain

    base = from_settings()
    everything = {model_id: {Capability.JSON_MODE} for model_id in base.models}
    # One tier's model is deliberately left unprobed, so it cannot satisfy the
    # requirement and must not appear anywhere in the chain.
    without = base.by_tier[Tier.CHEAP]
    everything.pop(without)

    catalogue = _catalogue_with(everything)
    requirements = ModelRequirements(capabilities=[Capability.JSON_MODE])
    first = resolve(requirements, catalogue=catalogue, requested_by="hermes")

    offered = [step.model.model_id for step in chain(first, requirements, catalogue=catalogue)]

    assert without not in offered, (
        f"{without} satisfies nothing and was offered as a fallback, so a failure "
        "of the first choice would silently drop the declared capability"
    )
    assert all(
        Capability.JSON_MODE in catalogue.models[model_id].capabilities for model_id in offered
    )


def test_the_chain_leads_with_the_resolved_choice() -> None:
    """Not reordered by price or latency. A cheaper model that satisfies the
    requirements is still a different model, and reordering would make the
    fallback path prefer something the tier binding did not choose."""
    from core.contracts.llm import ModelRequirements
    from core.llm.fallback import chain

    catalogue = _catalogue_with({m: {Capability.JSON_MODE} for m in from_settings().models})
    requirements = ModelRequirements(capabilities=[Capability.JSON_MODE])
    first = resolve(requirements, catalogue=catalogue, requested_by="hermes")

    offered = chain(first, requirements, catalogue=catalogue)

    assert offered[0].model.model_id == first.model.model_id


def test_a_model_bound_to_two_tiers_appears_once() -> None:
    """Retrying the same model twice is one wasted call and one misleading
    `rejected` entry.

    The catalogue is built here rather than from settings, because in the
    configured one every tier points at a DIFFERENT model - so a test using it
    asserts a property nothing could violate. Two tiers sharing a model is a
    normal configuration and it is the only shape this rule applies to.
    """
    from core.contracts.llm import ModelRequirements, Tier
    from core.llm.fallback import chain

    base = from_settings()
    shared = base.by_tier[Tier.BALANCED]
    catalogue = Catalogue(
        providers=base.providers,
        models={
            model_id: descriptor.model_copy(
                update={"capabilities": [Capability.JSON_MODE], "last_probed_at": NOW}
            )
            for model_id, descriptor in base.models.items()
        },
        # Every tier on one model. Without a dedup, the chain would offer it three times.
        by_tier=dict.fromkeys(Tier, shared),
    )

    requirements = ModelRequirements(capabilities=[Capability.JSON_MODE])
    first = resolve(requirements, catalogue=catalogue, requested_by="hermes")

    offered = [step.model.model_id for step in chain(first, requirements, catalogue=catalogue)]

    assert offered == [shared], f"the same model was offered {len(offered)} times: {offered}"


def test_the_cost_decision_is_the_one_guardrails_makes() -> None:
    """Delphi supplies the price; guardrails decide. A gateway with its own copy
    is a second policy nobody thinks to check when the first one changes."""
    from core.guardrails.budget import within_cost_ceiling
    from core.llm.gateway import within_budget

    assert within_budget is within_cost_ceiling


def test_an_unpriced_completion_is_not_treated_as_free_or_refused() -> None:
    """Refusing would make every provider that does not price its responses
    unusable; pretending zero would make them look free. Neither is honest."""
    from core.guardrails.budget import within_cost_ceiling

    assert within_cost_ceiling(None, 0.01) is True
    assert within_cost_ceiling(0.005, 0.01) is True
    assert within_cost_ceiling(0.02, 0.01) is False
    assert within_cost_ceiling(0.02, None) is True
