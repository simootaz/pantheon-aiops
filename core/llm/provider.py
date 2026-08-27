"""The adapter protocol every dialect implements.

One Protocol, four wire formats. The gateway holds a `Provider` and never knows
which dialect is behind it - that is the whole point of the abstraction.

WHAT IS ON THE PROTOCOL AND WHAT IS NOT
----------------------------------------
`complete` and `list_models` only. `stream` and `probe` are named in ADR 0004
and belong to later phases: streaming has no consumer until the AG-UI endpoint
exists, and probing is Phase 4's "Test connection" button. Declaring them now
would put two methods on every adapter that nothing calls and nothing tests,
which is how a Protocol stops describing what is actually implemented.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from core.contracts.llm import Capability


@dataclass(frozen=True)
class Completion:
    """One model response, and what it cost to get.

    Token counts are carried rather than recomputed. A caller that re-tokenises
    to estimate usage gets a different number from the provider's own, and the
    two then disagree in the audit trail - which is the same reason
    `MetricWindowPayload` carries `deviation_sigma` instead of letting each
    consumer recompute it.
    """

    text: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Set when the provider reports one. `None` means "not reported", which is
    #: different from zero and must not be rendered as free.
    cost: float | None = None
    finish_reason: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ProviderError(RuntimeError):
    """The provider could not answer.

    Carries `retryable` so the fallback chain can tell a rate limit from a
    malformed request. Retrying a 400 forever is how a budget disappears.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class Provider(Protocol):
    """What every dialect adapter offers the gateway."""

    @property
    def provider_id(self) -> str:
        """Which configured provider this speaks to."""
        ...

    async def complete(
        self,
        *,
        model_id: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> Completion:
        """One request, one response. Raises `ProviderError` on failure."""
        ...

    async def list_models(self) -> list[str]:
        """Model ids this provider exposes, for catalogue construction."""
        ...


@dataclass
class RecordingProvider:
    """A provider that answers from a script, for tests.

    Lives beside the Protocol rather than in a test module because the gateway's
    own tests, the resolver's, and any future agent's all need one - and three
    copies of a fake drift apart until they are testing three different things.
    """

    provider_id: str = "recording"
    reply: str = "ok"
    models: list[str] = field(default_factory=list)
    error: ProviderError | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def complete(
        self,
        *,
        model_id: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> Completion:
        self.calls.append(
            {
                "model_id": model_id,
                "prompt": prompt,
                "system": system,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        if self.error is not None:
            raise self.error
        return Completion(
            text=self.reply,
            model_id=model_id,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(self.reply.split()),
        )

    async def list_models(self) -> list[str]:
        return list(self.models)


#: Capabilities every `chat_completions` provider is assumed to have without
#: probing. Deliberately minimal: `TOOL_USE` and `VISION` vary by model even
#: within one provider, and assuming them is how an agent that declared
#: `TOOL_USE` receives a model without it and produces confident nonsense.
BASELINE_CAPABILITIES: frozenset[Capability] = frozenset({Capability.STREAMING})
