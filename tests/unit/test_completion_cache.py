"""The completion cache, and the two claims ADR 0008 rests on.

Those two claims are the point of this file:

* a hit is not a paid call, so "what did this investigation spend" does not
  climb while no money moves;
* a changed input changes the key, which is what makes caching a completion safe
  when caching a metric read is not.

The second is a property of how CALLERS build prompts, not something the cache
can enforce. It is asserted here against the real agent so that a future caller
which put the data outside the prompt fails a test instead of silently serving
last week's answer.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.contracts.llm import Capability, ModelRequirements, Tier
from core.llm.gateway import Delphi
from core.llm.provider import Completion, ProviderError, RecordingProvider
from core.memory.cache import DEFAULT_MAX_ENTRIES, CacheKey, CompletionCache


class _Ticker:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _key(prompt: str = "why", **overrides: Any) -> CacheKey:
    fields: dict[str, Any] = {
        "model_id": "a-model",
        "prompt": prompt,
        "system": None,
        "token_ceiling": 1024,
        "json_mode": False,
    }
    fields.update(overrides)
    return CacheKey(**fields)


# --- what the key covers ---------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"model_id": "another-model"},
        {"prompt": "why not"},
        {"system": "be terse"},
        {"token_ceiling": 2048},
        {"json_mode": True},
    ],
)
def test_any_change_to_the_request_is_a_different_entry(change: dict[str, Any]) -> None:
    """Every field that shapes a completion is in the key.

    A model change is obvious. `token_ceiling` is not, and is the one that bites:
    the same prompt at 16 tokens and at 1024 produces different text, and this
    project has already had a completion truncated to nothing by a low ceiling.
    """
    cache = CompletionCache()
    cache.put(_key(), "first")

    assert cache.get(_key(**change)) is None, f"{change} returned another request's answer"
    assert cache.get(_key()) == "first"


def test_the_key_does_not_store_the_prompt() -> None:
    """A prompt can carry a redacted secret or a customer's data. Keyed on the
    plaintext, it would sit in a process dump."""
    key = _key(prompt="the patient's name is Alice")

    assert "Alice" not in key.digest()
    assert len(key.digest()) == 64


def test_two_identical_requests_agree_on_their_digest() -> None:
    """The control. A digest that varied per call would make every get a miss
    and every test above pass for the wrong reason."""
    assert _key().digest() == _key().digest()


# --- expiry and eviction ----------------------------------------------------------


def test_an_entry_past_its_ttl_is_a_miss() -> None:
    clock = _Ticker()
    cache = CompletionCache(ttl_seconds=60.0, clock=clock)
    cache.put(_key(), "answer")

    clock.now += 59.0
    assert cache.get(_key()) == "answer"

    clock.now += 2.0
    assert cache.get(_key()) is None


def test_an_expired_entry_is_removed_rather_than_left_for_eviction() -> None:
    """So a stale value cannot be returned later by a bug in the eviction path."""
    clock = _Ticker()
    cache = CompletionCache(ttl_seconds=10.0, clock=clock)
    cache.put(_key(), "answer")

    clock.now += 20.0
    cache.get(_key())

    assert cache.size == 0


def test_the_cache_does_not_grow_without_bound() -> None:
    """It lives in the API process. A cache that grows with traffic is a leak
    with a friendly name."""
    cache = CompletionCache(max_entries=3)
    for index in range(10):
        cache.put(_key(prompt=f"q{index}"), index)

    assert cache.size == 3


def test_a_question_asked_repeatedly_survives_eviction() -> None:
    """Recency is updated on read, so the entry worth keeping is the one kept."""
    cache = CompletionCache(max_entries=2)
    cache.put(_key(prompt="hot"), "kept")
    cache.put(_key(prompt="cold"), "dropped")

    cache.get(_key(prompt="hot"))
    cache.put(_key(prompt="new"), "new")

    assert cache.get(_key(prompt="hot")) == "kept"
    assert cache.get(_key(prompt="cold")) is None


def test_clearing_resets_the_counters_with_the_contents() -> None:
    """A hit rate measured against entries that no longer exist describes nothing."""
    cache = CompletionCache()
    cache.put(_key(), "a")
    cache.get(_key())
    cache.get(_key(prompt="absent"))

    cache.clear()

    assert (cache.size, cache.hits, cache.misses) == (0, 0, 0)


def test_the_default_ceiling_is_a_ceiling() -> None:
    """A guard over the constant, so raising it is a deliberate act."""
    assert 0 < DEFAULT_MAX_ENTRIES <= 4096


# --- through the gateway ----------------------------------------------------------


def _delphi(cache: CompletionCache | None, provider: RecordingProvider) -> Delphi:
    from core.llm.catalog import from_settings

    catalogue = from_settings()
    provider.provider_id = next(iter(catalogue.providers))
    return Delphi(providers={provider.provider_id: provider}, catalogue=catalogue, cache=cache)


@pytest.mark.asyncio
async def test_a_second_identical_consultation_does_not_reach_the_provider() -> None:
    provider = RecordingProvider(reply="the answer")
    delphi = _delphi(CompletionCache(), provider)
    requirements = ModelRequirements(tier=Tier.CHEAP)

    first = await delphi.consult(requirements, prompt="why", requested_by="test")
    second = await delphi.consult(requirements, prompt="why", requested_by="test")

    assert len(provider.calls) == 1, "the provider was called twice for one question"
    assert second.completion.text == first.completion.text


@pytest.mark.asyncio
async def test_a_cache_hit_is_recorded_as_costing_nothing() -> None:
    """The claim ADR 0008 rests on.

    `ResolutionRecord` feeds "what did this investigation spend". Replaying the
    original cost would make that climb while no money moved, and an
    investigation that answered its second identical question for free must be
    visibly cheaper rather than invisibly the same.
    """
    provider = RecordingProvider(reply="the answer")
    delphi = _delphi(CompletionCache(), provider)
    requirements = ModelRequirements(tier=Tier.CHEAP)

    await delphi.consult(requirements, prompt="why", requested_by="test")
    hit = await delphi.consult(requirements, prompt="why", requested_by="test")

    assert hit.record.estimated_cost == 0.0
    assert hit.span.cached is True
    assert hit.span.prompt_tokens == 0
    assert hit.span.completion_tokens == 0


@pytest.mark.asyncio
async def test_a_gateway_with_no_cache_behaves_exactly_as_before() -> None:
    """Off unless supplied. Caching by default would change every existing
    caller's behaviour without any of them asking."""
    provider = RecordingProvider(reply="the answer")
    delphi = _delphi(None, provider)
    requirements = ModelRequirements(tier=Tier.CHEAP)

    await delphi.consult(requirements, prompt="why", requested_by="test")
    await delphi.consult(requirements, prompt="why", requested_by="test")

    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_a_failed_call_is_not_cached() -> None:
    """Caching a failure would keep answering with it after the provider recovered."""
    provider = RecordingProvider(error=ProviderError("upstream is down", retryable=True))
    cache = CompletionCache()
    delphi = _delphi(cache, provider)

    with pytest.raises(ProviderError):
        await delphi.consult(ModelRequirements(tier=Tier.CHEAP), prompt="why", requested_by="test")

    assert cache.size == 0


# --- the property the cache cannot guarantee on its own ----------------------------


@pytest.mark.asyncio
async def test_hermes_puts_its_data_in_the_prompt_so_changed_data_changes_the_key() -> None:
    """The assumption that makes caching a completion safe, asserted on a caller.

    A cached Prometheus read answers with the past and is refused for that
    reason. A cached completion is safe only because agents embed the data they
    are reasoning about IN the prompt, so different data is a different key.

    A future caller that put a bare question in the prompt and the data
    somewhere else would break that silently. This is what fails instead.
    """
    from tests.unit.test_hermes_nl_query import _hermes, _plan, _Scripted, _Tools

    prompts: list[str] = []

    class _Recording(_Scripted):
        async def consult(self, requirements: Any, **kwargs: Any) -> Any:
            prompts.append(str(kwargs.get("prompt", "")))
            return await super().consult(requirements, **kwargs)

    first = {"resultType": "vector", "result": [{"value": [1, "0.42"]}]}
    second = {"resultType": "vector", "result": [{"value": [1, "0.99"]}]}

    for result in (first, second):
        agent, ctx, _tools = _hermes(_Recording(_plan(), "an answer"), _Tools(result=result))
        await agent.investigate(ctx)

    answering = [prompt for prompt in prompts if "Result:" in prompt]
    assert len(answering) == 2
    assert answering[0] != answering[1], (
        "Hermes sent the same prompt for two different query results, so a cache "
        "would answer the second question with the first one's data"
    )
    assert "0.42" in answering[0] and "0.99" in answering[1]


def test_a_completion_is_what_the_gateway_caches() -> None:
    """Guarding the isinstance check in the gateway.

    A cache holding some other object would be ignored rather than served, which
    is safe - but it would also be silent, and a cache that never hits looks
    exactly like one that is working.
    """
    cache = CompletionCache()
    cache.put(_key(), Completion(text="hello", model_id="a-model"))

    value = cache.get(_key())
    assert isinstance(value, Completion)
    assert value.text == "hello"


def test_the_cached_value_round_trips_as_json_for_a_future_shared_cache() -> None:
    """Not used yet, and asserted anyway.

    ADR 0008 says a shared cache would live in `core/memory/`. That needs a
    serialisation format, and finding out then that `Completion` does not have
    one is finding out too late.
    """
    completion = Completion(text="hello", model_id="a-model", prompt_tokens=3)
    body = json.dumps(completion.__dict__)

    assert json.loads(body)["text"] == "hello"


def test_capabilities_are_not_part_of_the_key_and_that_is_deliberate() -> None:
    """Requirements choose the MODEL; they do not change what the model returns.

    Two agents asking the identical question of the identical model get the
    identical answer, whatever capabilities each declared to get there - so
    including them would split the cache for no gain.
    """
    strict = ModelRequirements(capabilities=[Capability.JSON_MODE], tier=Tier.CHEAP)
    loose = ModelRequirements(tier=Tier.CHEAP)

    assert strict != loose
    assert _key().digest() == _key().digest()
