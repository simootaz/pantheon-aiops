"""Delphi against a real provider.

Every other Delphi test runs behind an injected transport, so no request has
left the machine. That proves the adapter matches what I *believe* a provider
returns - and this repository has a record of that belief being wrong: the
pushgateway answering 202 for a group that did not exist, `_node_disk` never
calling `_baseline`. A mock written from the same misunderstanding as the code
agrees with it perfectly.

So this one talks to whatever `LLM_*` is configured. It is provider-agnostic on
purpose: the point of ADR 0004 is that swapping vendors is a settings change, and
a gate hardcoded to one vendor would be testing the vendor rather than the
abstraction.

**Skipped, not failed, when no key is configured.** A developer without an API
key has not broken anything, and a red gate that means "you did not sign up for
a third-party service" trains people to ignore red gates.

Run with:  make test-delphi

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import pytest

from core.config import get_settings
from core.contracts.llm import AuthMode, ModelRequirements, Tier
from core.llm.catalog import from_settings
from core.llm.gateway import Delphi
from core.llm.provider import ProviderError
from core.llm.providers.chat_completions import ChatCompletionsProvider

pytestmark = pytest.mark.integration

SETTINGS = get_settings()
DELPHI = SETTINGS.delphi

_needs_key = DELPHI.auth_mode is not AuthMode.NONE and not DELPHI.api_key
requires_provider = pytest.mark.skipif(
    _needs_key,
    reason=(
        f"{DELPHI.provider_id} needs LLM_API_KEY and none is set. Put it in the "
        "repository-root .env, which is the file core/config.py reads."
    ),
)


def _provider() -> ChatCompletionsProvider:
    catalogue = from_settings()
    return ChatCompletionsProvider(
        catalogue.providers[DELPHI.provider_id],
        api_key=DELPHI.api_key.get_secret_value() if DELPHI.api_key else None,
        timeout_seconds=float(DELPHI.request_timeout_seconds),
    )


@requires_provider
@pytest.mark.asyncio
async def test_the_configured_provider_answers_a_real_prompt() -> None:
    """The whole point: a request leaves this machine and a model answers it."""
    provider = _provider()
    completion = await provider.complete(
        model_id=DELPHI.tier_cheap_model,
        prompt="Reply with exactly the word: pantheon",
        system="You answer in one word, lowercase, no punctuation.",
        # Not 16. A reasoning model spends tokens thinking before it answers, so
        # a tight cap returns nothing at all - which the adapter now reports as
        # truncation rather than as an empty answer. Found by this gate.
        max_tokens=512,
    )

    assert completion.text.strip(), "the provider returned an empty completion"
    assert "pantheon" in completion.text.lower(), (
        f"the model was asked for one word and said: {completion.text!r}"
    )
    assert completion.model_id, "the response named no model"
    assert completion.prompt_tokens > 0, (
        "the provider reported no prompt tokens; the usage block was not read, or "
        "this provider does not report one - either way the audit trail is blank"
    )


@requires_provider
@pytest.mark.asyncio
async def test_a_wrong_model_id_fails_saying_which_one() -> None:
    """Model ids move. A vendor deprecation must not read as a broken adapter.

    The failure has to name the id that was rejected, because the fix is an edit
    to `LLM_TIER_*_MODEL` and nobody can make it from "the request failed".
    """
    provider = _provider()
    with pytest.raises(ProviderError) as raised:
        await provider.complete(
            model_id="a-model-that-was-never-released", prompt="hello", max_tokens=8
        )

    message = str(raised.value)
    assert DELPHI.provider_id in message, "the failure does not say which provider refused"
    assert "a-model-that-was-never-released" in message, (
        "the failure does not name the model id that was refused, so nobody can "
        "tell it from an auth failure - which is exactly what happened on the "
        f"first live run of this gate: {message}"
    )
    assert raised.value.retryable is False, (
        "an unknown model id was marked retryable, so the chain will spend the "
        "budget asking again for something that does not exist"
    )


@requires_provider
@pytest.mark.asyncio
async def test_the_gateway_reaches_a_model_without_anyone_naming_one() -> None:
    """ADR 0004's invariant, end to end against a live provider.

    The caller supplies a tier and a prompt. Nothing in this test names a model;
    the id in the record came out of the catalogue.
    """
    delphi = Delphi(providers={DELPHI.provider_id: _provider()})

    result = await delphi.consult(
        ModelRequirements(tier=Tier.CHEAP),
        prompt="Reply with exactly the word: resolved",
        requested_by="delphi-live-gate",
        max_tokens=512,
    )

    assert "resolved" in result.completion.text.lower()
    assert result.record.chosen.model_id == DELPHI.tier_cheap_model, (
        f"resolved to {result.record.chosen.model_id}, which is not the configured "
        f"cheap tier {DELPHI.tier_cheap_model}"
    )
    assert result.record.requested_by == "delphi-live-gate"
    assert result.span.total_tokens > 0, "the span recorded no tokens for a real call"
    assert result.span.prompt is None, (
        "the prompt text reached the span; the default must carry a digest only"
    )
    assert result.span.duration_ms >= 0


@requires_provider
@pytest.mark.asyncio
async def test_json_mode_produces_json_when_the_model_supports_it() -> None:
    """Declared as a capability, so it has to actually work where it is claimed.

    Not asserted as valid JSON on the nose - some models wrap it in prose even in
    JSON mode, and this gate is about the request being *accepted and honoured*
    rather than about model quality.
    """
    import json

    provider = _provider()
    completion = await provider.complete(
        model_id=DELPHI.tier_cheap_model,
        prompt='Return a JSON object with one key "status" set to "ok".',
        max_tokens=512,
        json_mode=True,
    )

    try:
        parsed = json.loads(completion.text)
    except ValueError:  # pragma: no cover - depends on the model, not the adapter
        pytest.skip(f"{DELPHI.tier_cheap_model} did not return parseable JSON in JSON mode")

    assert isinstance(parsed, dict), f"JSON mode returned {type(parsed).__name__}"


@requires_provider
@pytest.mark.asyncio
async def test_the_provider_lists_the_models_it_serves() -> None:
    """`/models` is optional, so a provider that lacks it must not fail the gate.

    `catalog.enumerate_models` already falls back to the configured list; this
    checks the adapter parses a real listing when one is offered.
    """
    try:
        models = await _provider().list_models()
    except ProviderError as unsupported:
        pytest.skip(f"{DELPHI.provider_id} does not serve /models: {unsupported}")

    assert models, "the provider answered /models with nothing"
    assert all(isinstance(model, str) for model in models)
    assert DELPHI.tier_cheap_model in models, (
        f"the configured cheap tier {DELPHI.tier_cheap_model!r} is not in the "
        f"{len(models)} models this provider serves. It has probably been "
        f"deprecated - edit LLM_TIER_CHEAP_MODEL. Available: {sorted(models)[:10]}"
    )
