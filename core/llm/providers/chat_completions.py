"""CHAT_COMPLETIONS dialect adapter - the reference implementation.

The highest-leverage adapter by a wide margin. Spoken by OpenRouter, Groq,
Together, DeepSeek, Mistral, vLLM, LM Studio, Ollama, OpenAI and most
self-hosted stacks - get this one right and 'any provider' is already mostly
true.

Written first; the other adapters follow its shape.

WHAT IT REFUSES TO GUESS
-------------------------
A response missing `choices`, or carrying an empty one, raises rather than
returning an empty string. A caller handed `""` cannot tell "the model said
nothing" from "the response was not the shape we expected", and the first is a
result while the second is a bug.

Usage is read where the provider reports it and left at zero where it does not.
Zero tokens is visibly wrong in an audit trail; an estimate is invisibly wrong.

A completion that is empty *because the model was cut off* raises too. The live
gate found this on its first green-ish run: `openai/gpt-oss-20b` is a reasoning
model, spent all 16 permitted tokens thinking, and returned `text=""` with
`finish_reason="length"`. Passing that back as an empty string hands the caller
the exact ambiguity this module exists to prevent - "the model said nothing"
against "the model never got to speak".

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from typing import Any

import httpx

from core.contracts.llm import AuthMode, ProviderConfig
from core.llm.provider import Completion, ProviderError

#: Status codes worth trying the next candidate for. A 400 means the request was
#: wrong and will be wrong again; retrying it forever is how a budget vanishes.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ChatCompletionsProvider:
    """One configured provider speaking the OpenAI chat-completions dialect."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._timeout = timeout_seconds
        #: Injectable so tests do not open sockets. On this platform a closed
        #: loopback port does not refuse promptly, so a real call in a unit test
        #: fails by hanging rather than by erroring.
        self._client = client

    @property
    def provider_id(self) -> str:
        return self._config.id

    async def complete(
        self,
        *,
        model_id: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> Completion:
        """One request, one response."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        payload = await self._post("/chat/completions", body)
        return _completion(payload, fallback_model=model_id)

    async def list_models(self) -> list[str]:
        """`GET /models`, which many gateways do not implement.

        A failure here is not fatal - `catalog.enumerate_models` falls back to
        the configured list - so this raises and lets the caller decide.
        """
        payload = await self._get("/models")
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [str(entry["id"]) for entry in data if isinstance(entry, dict) and "id" in entry]

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Auth as the provider expects it.

        The key is never logged from here. `tracing.py` redacts before emitting,
        and this module simply does not print.
        """
        headers = {"Content-Type": "application/json"}
        if not self._api_key:
            return headers
        if self._config.auth_mode is AuthMode.BEARER:
            headers["Authorization"] = f"Bearer {self._api_key}"
        elif self._config.auth_mode is AuthMode.HEADER_KEY:
            headers["x-api-key"] = self._api_key
        return headers

    def _params(self) -> dict[str, str]:
        if self._api_key and self._config.auth_mode is AuthMode.QUERY_PARAM:
            return {"key": self._api_key}
        return {}

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=body)

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._config.base_url.rstrip('/')}{path}"
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, url, headers=self._headers(), params=self._params(), **kwargs
                )
            else:  # pragma: no cover - exercised by the live gate, not by units
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(
                        method, url, headers=self._headers(), params=self._params(), **kwargs
                    )
        except httpx.HTTPError as unreachable:
            raise ProviderError(
                f"{self._config.id} at {url} could not be reached: {unreachable}",
                retryable=True,
            ) from unreachable

        if response.status_code >= 400:
            raise ProviderError(
                f"{self._config.id} answered {response.status_code} for {path}: "
                f"{response.text[:300]}",
                retryable=response.status_code in RETRYABLE_STATUS,
            )

        try:
            payload = response.json()
        except ValueError as malformed:
            raise ProviderError(
                f"{self._config.id} answered {response.status_code} with a body that is "
                f"not JSON: {response.text[:200]!r}",
                retryable=False,
            ) from malformed

        if not isinstance(payload, dict):
            raise ProviderError(
                f"{self._config.id} answered with {type(payload).__name__}, not an object",
                retryable=False,
            )
        return payload


def _completion(payload: dict[str, Any], *, fallback_model: str) -> Completion:
    """Read the response, or say plainly that it was not the expected shape."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(
            f"response carried no choices: {sorted(payload)}. An empty completion "
            "would be indistinguishable from a model that said nothing.",
            retryable=False,
        )

    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if text is None:
        raise ProviderError(
            "the first choice carried no message content; the response shape is not "
            "chat-completions",
            retryable=False,
        )

    finish_reason = str(first.get("finish_reason") or "") if isinstance(first, dict) else ""
    if not str(text).strip() and finish_reason == "length":
        raise ProviderError(
            "the model was cut off before it produced any content "
            f"(finish_reason={finish_reason!r}). Reasoning models spend tokens "
            "thinking before they answer, so a small max_tokens returns an empty "
            "string rather than a short one. Raise max_tokens.",
            retryable=False,
        )

    raw_usage = payload.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    return Completion(
        text=str(text),
        model_id=str(payload.get("model") or fallback_model),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        cost=None,
        finish_reason=finish_reason,
    )
