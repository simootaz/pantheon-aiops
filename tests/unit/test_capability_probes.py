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

from core.contracts.llm import Capability, ModelRequirements
from core.llm.capability_matrix import STALE_AFTER, CapabilityMatrix, Probed
from core.llm.catalog import from_settings
from core.llm.probe import PROBEABLE, probe_into, probe_model
from core.llm.provider import BASELINE_CAPABILITIES, ProviderError, RecordingProvider
from core.llm.resolver import Unresolvable, resolve

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class _Ticker:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _provider(reply: str = '{"ok": true}', **kwargs: object) -> RecordingProvider:
    provider = RecordingProvider(reply=reply, **kwargs)  # type: ignore[arg-type]
    provider.provider_id = "groq"
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
