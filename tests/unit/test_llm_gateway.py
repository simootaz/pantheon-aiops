"""The gateway, the chat-completions adapter and the span it emits.

Every test here is offline. The adapter takes an injected client for exactly
that reason: on this platform a closed loopback port does not refuse promptly,
so a real call in a unit test fails by hanging rather than by erroring.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
from typing import Any

import httpx
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
from core.llm.catalog import Catalogue
from core.llm.gateway import BudgetExceeded, Delphi, within_budget
from core.llm.provider import ProviderError, RecordingProvider
from core.llm.providers.chat_completions import ChatCompletionsProvider
from core.llm.resolver import Bindings, Unresolvable
from core.llm.tracing import digest, span_for

PROVIDER = "test-provider"


def _config(auth: AuthMode = AuthMode.NONE) -> ProviderConfig:
    return ProviderConfig(
        id=PROVIDER,
        display_name="Test",
        dialect=Dialect.CHAT_COMPLETIONS,
        base_url="http://provider.invalid/v1",
        auth_mode=auth,
    )


def _model(model_id: str, *, capabilities: list[Capability] | None = None) -> ModelDescriptor:
    return ModelDescriptor(
        provider_id=PROVIDER,
        model_id=model_id,
        context_window=128_000,
        capabilities=capabilities if capabilities is not None else [Capability.STREAMING],
    )


def _catalogue(**models: ModelDescriptor) -> Catalogue:
    resolved = {name: models.get(name, _model(name)) for name in ("cheap", "balanced", "frontier")}
    return Catalogue(
        providers={PROVIDER: _config()},
        models={model.model_id: model for model in resolved.values()},
        by_tier={
            Tier.CHEAP: resolved["cheap"].model_id,
            Tier.BALANCED: resolved["balanced"].model_id,
            Tier.FRONTIER: resolved["frontier"].model_id,
        },
    )


def _transport(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


CHAT_RESPONSE = {
    "model": "balanced",
    "choices": [{"message": {"content": "the answer"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 4},
}


# --- the adapter ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_adapter_sends_the_dialect_the_provider_expects() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json=CHAT_RESPONSE)

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        completion = await provider.complete(
            model_id="balanced", prompt="why", system="be terse", max_tokens=32
        )

    # Parsed, not string-matched: httpx serialises compactly, so `"role": "system"`
    # with a space never appears and the assertion would fail on a correct body.
    body = json.loads(seen["body"])
    assert seen["url"].endswith("/chat/completions")
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["messages"][1] == {"role": "user", "content": "why"}
    assert body["max_tokens"] == 32
    assert body["model"] == "balanced"
    assert completion.text == "the answer"
    assert completion.prompt_tokens == 11
    assert completion.completion_tokens == 4
    assert completion.finish_reason == "stop"


@pytest.mark.asyncio
async def test_json_mode_is_requested_only_when_asked_for() -> None:
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read().decode())
        return httpx.Response(200, json=CHAT_RESPONSE)

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        await provider.complete(model_id="m", prompt="p")
        await provider.complete(model_id="m", prompt="p", json_mode=True)

    assert "response_format" not in json.loads(bodies[0])
    assert json.loads(bodies[1])["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_a_bearer_key_is_sent_as_the_auth_mode_declares() -> None:
    headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        headers.update(request.headers)
        return httpx.Response(200, json=CHAT_RESPONSE)

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(
            _config(AuthMode.BEARER), api_key="s3cret", client=client
        )
        await provider.complete(model_id="m", prompt="p")

    assert headers["authorization"] == "Bearer s3cret"


@pytest.mark.asyncio
async def test_a_response_with_no_choices_raises_rather_than_returning_nothing() -> None:
    """An empty completion is indistinguishable from a model that said nothing.

    One is a result and the other is a bug, and a caller handed `""` cannot tell
    them apart.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "choices": []})

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="no choices"):
            await provider.complete(model_id="m", prompt="p")


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_reported_as_such() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="not JSON"):
            await provider.complete(model_id="m", prompt="p")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (503, True), (500, True), (400, False), (401, False), (404, False)],
)
async def test_only_transient_statuses_are_marked_retryable(status: int, retryable: bool) -> None:
    """Retrying a 400 forever is how a budget disappears."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "no"})

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError) as raised:
            await provider.complete(model_id="m", prompt="p")

    assert raised.value.retryable is retryable


@pytest.mark.asyncio
async def test_model_listing_reads_ids_and_tolerates_a_missing_endpoint() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "a"}, {"no-id": 1}, {"id": "b"}]})

    async with _transport(handler) as client:
        assert await ChatCompletionsProvider(_config(), client=client).list_models() == ["a", "b"]

    def empty(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list"})

    async with _transport(empty) as client:
        assert await ChatCompletionsProvider(_config(), client=client).list_models() == []


# --- the gateway ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_consulting_returns_the_completion_with_the_record_that_explains_it() -> None:
    provider = RecordingProvider(provider_id=PROVIDER, reply="because")
    delphi = Delphi(providers={PROVIDER: provider}, catalogue=_catalogue())

    result = await delphi.consult(
        ModelRequirements(tier=Tier.BALANCED), prompt="why", requested_by="delphi-test"
    )

    assert result.completion.text == "because"
    assert result.record.chosen.model_id == "balanced"
    assert result.record.matched_step is ResolutionStep.TIER_DEFAULT
    assert result.record.requested_by == "delphi-test"
    assert provider.calls[0]["model_id"] == "balanced"


@pytest.mark.asyncio
async def test_an_agent_cannot_name_a_model_through_consult() -> None:
    """ADR 0004's invariant, at the only door an agent goes through."""
    import inspect

    parameters = set(inspect.signature(Delphi.consult).parameters)
    assert parameters == {
        "self",
        "requirements",
        "prompt",
        "requested_by",
        "system",
        "max_tokens",
        "json_mode",
    }, parameters


@pytest.mark.asyncio
async def test_a_retryable_failure_moves_to_the_next_candidate() -> None:
    class _FlakyThenFine:
        provider_id = PROVIDER

        def __init__(self) -> None:
            self.tried: list[str] = []

        async def complete(self, *, model_id: str, prompt: str, **_: Any) -> Any:
            self.tried.append(model_id)
            if len(self.tried) == 1:
                raise ProviderError("rate limited", retryable=True)
            return await RecordingProvider(reply="second").complete(
                model_id=model_id, prompt=prompt
            )

        async def list_models(self) -> list[str]:
            return []

    provider = _FlakyThenFine()
    delphi = Delphi(providers={PROVIDER: provider}, catalogue=_catalogue())

    result = await delphi.consult(
        ModelRequirements(tier=Tier.BALANCED), prompt="why", requested_by="hermes"
    )

    assert len(provider.tried) >= 2, "the chain did not move on after a retryable failure"
    assert result.record.fallback_used is True, (
        "a run that fell back must say so, or nobody can tell it from a first-choice answer"
    )
    assert any("rate limited" in reason for reason in result.record.rejected)


@pytest.mark.asyncio
async def test_a_non_retryable_failure_stops_immediately() -> None:
    """A 400 will be a 400 again. Walking the chain would spend the budget proving it."""
    provider = RecordingProvider(
        provider_id=PROVIDER, error=ProviderError("malformed", retryable=False)
    )
    delphi = Delphi(providers={PROVIDER: provider}, catalogue=_catalogue())

    with pytest.raises(ProviderError, match="malformed"):
        await delphi.consult(ModelRequirements(), prompt="why", requested_by="hermes")

    assert len(provider.calls) == 1, f"the chain kept going after a hard failure: {provider.calls}"


@pytest.mark.asyncio
async def test_the_chain_never_relaxes_a_declared_capability() -> None:
    """The failure that would otherwise be worst exactly when the system is struggling.

    Only `frontier` has JSON_MODE. When it fails retryably there is nothing else
    that satisfies the requirement, so the call fails rather than quietly using
    a model without it.
    """
    catalogue = _catalogue(
        frontier=_model("frontier", capabilities=[Capability.STREAMING, Capability.JSON_MODE]),
        balanced=_model("balanced", capabilities=[Capability.STREAMING]),
        cheap=_model("cheap", capabilities=[Capability.STREAMING]),
    )
    provider = RecordingProvider(
        provider_id=PROVIDER, error=ProviderError("overloaded", retryable=True)
    )
    delphi = Delphi(providers={PROVIDER: provider}, catalogue=catalogue)

    with pytest.raises(ProviderError, match="overloaded"):
        await delphi.consult(
            ModelRequirements(tier=Tier.FRONTIER, capabilities=[Capability.JSON_MODE]),
            prompt="why",
            requested_by="clio",
        )

    assert [call["model_id"] for call in provider.calls] == ["frontier"], (
        "the chain widened to a model without JSON_MODE, which is the silent "
        f"downgrade ADR 0004 forbids: {provider.calls}"
    )


@pytest.mark.asyncio
async def test_an_unresolvable_requirement_never_reaches_a_provider() -> None:
    provider = RecordingProvider(provider_id=PROVIDER)
    delphi = Delphi(providers={PROVIDER: provider}, catalogue=_catalogue())

    with pytest.raises(Unresolvable):
        await delphi.consult(
            ModelRequirements(capabilities=[Capability.VISION]),
            prompt="why",
            requested_by="aegis",
        )

    assert provider.calls == [], "a call was made for requirements nothing satisfied"


# --- the cost guard --------------------------------------------------------------


def test_an_unreported_cost_cannot_be_enforced_against() -> None:
    """Refusing it makes unpriced providers unusable; zeroing it makes them look free."""
    assert within_budget(None, 0.01) is True
    assert within_budget(0.005, 0.01) is True
    assert within_budget(0.02, 0.01) is False
    assert within_budget(0.02, None) is True


@pytest.mark.asyncio
async def test_exceeding_the_ceiling_stops_rather_than_downgrading() -> None:
    class _Pricey(RecordingProvider):
        async def complete(self, *, model_id: str, prompt: str, **kwargs: Any) -> Any:
            completion = await super().complete(model_id=model_id, prompt=prompt, **kwargs)
            return type(completion)(**{**completion.__dict__, "cost": 5.0})

    delphi = Delphi(providers={PROVIDER: _Pricey(provider_id=PROVIDER)}, catalogue=_catalogue())

    with pytest.raises(BudgetExceeded, match="Stopping rather than moving to a cheaper model"):
        await delphi.consult(
            ModelRequirements(max_cost_per_call=0.01), prompt="why", requested_by="moira"
        )


@pytest.mark.asyncio
async def test_the_cost_decision_is_one_injectable_function() -> None:
    """Phase 3 moves it into core/guardrails/budget.py.

    Asserting it is substitutable now is what makes that a substitution rather
    than a rewrite.
    """
    delphi = Delphi(
        providers={PROVIDER: RecordingProvider(provider_id=PROVIDER)},
        catalogue=_catalogue(),
        cost_guard=lambda _cost, _ceiling: False,
    )
    with pytest.raises(BudgetExceeded):
        await delphi.consult(ModelRequirements(), prompt="why", requested_by="moira")


# --- the span -----------------------------------------------------------------------


def test_the_span_carries_a_digest_rather_than_the_prompt() -> None:
    """A prompt assembled from an Investigation carries whatever the connectors
    returned. Redaction removes the secrets Cerberus knows about, and cannot
    remove the ones nobody registered."""
    span = span_for(
        requested_by="lethe",
        model=_model("balanced"),
        matched_step=ResolutionStep.TIER_DEFAULT,
        prompt="a prompt with pod-7 in it",
    )

    assert span.prompt is None, "the prompt text reached the span by default"
    assert span.prompt_digest == digest("a prompt with pod-7 in it")
    assert span.prompt_chars == len("a prompt with pod-7 in it")


def test_a_digest_distinguishes_two_prompts_and_matches_a_repeat() -> None:
    """What the span is actually asked: were these two runs the same call?"""
    assert digest("one") != digest("two")
    assert digest("one") == digest("one")


def test_including_the_prompt_is_deliberate_and_redacted() -> None:
    span = span_for(
        requested_by="lethe",
        model=_model("balanced"),
        matched_step=ResolutionStep.TIER_DEFAULT,
        prompt="token=glpat-AAAAAAAAAAAAAAAAAAAA and other text",
        include_prompt=True,
        secrets=["glpat-AAAAAAAAAAAAAAAAAAAA"],
    )

    assert span.prompt is not None
    assert "glpat-AAAAAAAAAAAAAAAAAAAA" not in span.prompt, (
        f"a registered secret survived into the span: {span.prompt!r}"
    )


@pytest.mark.asyncio
async def test_the_span_records_what_the_call_cost_in_tokens_and_time() -> None:
    delphi = Delphi(
        providers={PROVIDER: RecordingProvider(provider_id=PROVIDER, reply="two words")},
        catalogue=_catalogue(),
    )
    result = await delphi.consult(ModelRequirements(), prompt="one two three", requested_by="clio")

    assert result.span.prompt_tokens == 3
    assert result.span.completion_tokens == 2
    assert result.span.total_tokens == 5
    assert result.span.duration_ms >= 0
    assert result.span.failed is False


@pytest.mark.asyncio
async def test_a_binding_is_honoured_through_the_gateway() -> None:
    delphi = Delphi(
        providers={PROVIDER: RecordingProvider(provider_id=PROVIDER)},
        catalogue=_catalogue(),
        bindings=Bindings(per_agent={"hermes": "frontier"}),
    )
    result = await delphi.consult(
        ModelRequirements(tier=Tier.CHEAP), prompt="why", requested_by="hermes"
    )
    assert result.record.chosen.model_id == "frontier"
    assert result.record.matched_step is ResolutionStep.AGENT_BINDING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "check"),
    [
        (AuthMode.HEADER_KEY, lambda r: r.headers.get("x-api-key") == "s3cret"),
        (AuthMode.QUERY_PARAM, lambda r: "key=s3cret" in str(r.url)),
        (AuthMode.NONE, lambda r: "authorization" not in r.headers and "key=" not in str(r.url)),
    ],
)
async def test_every_auth_mode_puts_the_credential_where_it_belongs(
    mode: AuthMode, check: Any
) -> None:
    """Four modes exist because providers genuinely differ.

    A credential sent the wrong way is a 401 that looks like a bad key, which
    sends whoever debugs it to rotate a key that was fine.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CHAT_RESPONSE)

    async with _transport(handler) as client:
        key = None if mode is AuthMode.NONE else "s3cret"
        provider = ChatCompletionsProvider(_config(mode), api_key=key, client=client)
        await provider.complete(model_id="m", prompt="p")

    assert check(seen[0]), f"{mode.value} did not carry the credential as declared"


@pytest.mark.asyncio
async def test_a_provider_that_cannot_be_reached_is_retryable() -> None:
    """An unreachable host is transient by nature; a malformed request is not."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="could not be reached") as raised:
            await provider.complete(model_id="m", prompt="p")

    assert raised.value.retryable is True


@pytest.mark.asyncio
async def test_a_json_body_that_is_not_an_object_is_refused() -> None:
    """Some gateways answer 200 with a bare string on error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="not an object"):
            await provider.complete(model_id="m", prompt="p")


@pytest.mark.asyncio
async def test_a_choice_with_no_message_content_is_refused() -> None:
    """The shape is not chat-completions, and returning "" would hide that."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"text": "legacy completion shape"}]})

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="no message content"):
            await provider.complete(model_id="m", prompt="p")


@pytest.mark.asyncio
async def test_a_response_without_usage_reports_zero_rather_than_an_estimate() -> None:
    """Zero tokens is visibly wrong in an audit trail; an estimate is invisibly wrong."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        completion = await provider.complete(model_id="fallback-id", prompt="p")

    assert completion.prompt_tokens == 0
    assert completion.completion_tokens == 0
    assert completion.model_id == "fallback-id", (
        "a response that named no model must fall back to the one that was asked for"
    )


def test_the_provider_id_is_the_configured_one() -> None:
    assert ChatCompletionsProvider(_config()).provider_id == PROVIDER


@pytest.mark.asyncio
async def test_a_completion_cut_off_before_it_spoke_is_reported_not_returned_empty() -> None:
    """Found by the live gate, on its first run that got past auth.

    `openai/gpt-oss-20b` is a reasoning model: it spent all 16 permitted tokens
    thinking and returned `text=""` with `finish_reason="length"`. Passing that
    back as an empty string hands the caller the exact ambiguity this adapter
    exists to prevent - "the model said nothing" against "the model never got to
    speak" - and the second has an obvious fix the first does not.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "reasoner",
                "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 93, "completion_tokens": 16},
            },
        )

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        with pytest.raises(ProviderError, match="cut off before it produced any content"):
            await provider.complete(model_id="reasoner", prompt="p", max_tokens=16)


@pytest.mark.asyncio
async def test_an_empty_answer_that_finished_normally_is_still_an_answer() -> None:
    """The other side of it. A model that stopped on its own and said nothing
    has answered - unhelpfully, but it answered, and that is not an error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            },
        )

    async with _transport(handler) as client:
        provider = ChatCompletionsProvider(_config(), client=client)
        completion = await provider.complete(model_id="m", prompt="p")

    assert completion.text == ""
    assert completion.finish_reason == "stop"
