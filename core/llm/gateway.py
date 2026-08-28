"""Delphi entrypoint - the only module agents call.

Takes ModelRequirements and a prompt, resolves a model, invokes the right
dialect adapter, records a ResolutionRecord on the Investigation and returns the
completion.

Agents pass requirements, never a model name. An agent that names a model is a
bug, not a shortcut.

THE FALLBACK CHAIN, AND WHERE IT STOPS
----------------------------------------
A retryable provider failure moves to the next candidate that *also satisfies
the requirements*. It never widens the search: a chain that relaxed a declared
capability under load would produce its worst output exactly when the system is
already struggling, and nobody would connect the two.

Cost enforcement is a hook, not a policy. `core/guardrails/budget.py` is Phase 3
and does not exist, so `max_cost_per_call` is checked here against what the
provider reports and the check is one injectable function - which is what makes
moving the decision later a substitution rather than a rewrite.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from core.contracts.llm import ModelRequirements, ResolutionRecord, Tier
from core.llm.catalog import Catalogue, from_settings
from core.llm.provider import Completion, Provider, ProviderError
from core.llm.resolver import Bindings, Resolution, Unresolvable, resolve
from core.llm.tracing import ModelCallSpan, span_for
from core.memory.cache import CacheKey, CompletionCache


class BudgetExceeded(RuntimeError):
    """The call would cost more than the requirements allow.

    A stop rather than a downgrade, for the same reason `Unresolvable` is: an
    agent quietly moved to a cheaper model produces worse output with no signal
    that anything changed.
    """


@dataclass
class Consultation:
    """What one `consult` produced, including why that model answered."""

    completion: Completion
    record: ResolutionRecord
    span: ModelCallSpan


#: The cost decision, as one function. Phase 3 replaces this with a call into
#: `core/guardrails/budget.py`; until then it enforces the declared ceiling and
#: nothing else, which is the narrowest thing that is still honest.
CostGuard = Callable[[float | None, float | None], bool]


def within_budget(cost: float | None, ceiling: float | None) -> bool:
    """Whether a reported cost is acceptable.

    An unreported cost passes. Refusing it would make every provider that does
    not price its responses unusable, and pretending it is zero would make them
    look free - the honest reading is that the ceiling cannot be enforced
    against a number nobody supplied, and `Completion.cost` stays `None` so a
    reader can see that.
    """
    if ceiling is None or cost is None:
        return True
    return cost <= ceiling


class Delphi:
    """The gateway. Agents hold one of these and call `consult`."""

    def __init__(
        self,
        *,
        providers: dict[str, Provider],
        catalogue: Catalogue | None = None,
        bindings: Bindings | None = None,
        cost_guard: CostGuard = within_budget,
        include_prompt_in_span: bool = False,
        cache: CompletionCache | None = None,
    ) -> None:
        self._providers = providers
        self._catalogue = catalogue or from_settings()
        self._bindings = bindings or Bindings()
        self._cost_guard = cost_guard
        self._include_prompt = include_prompt_in_span
        # Off unless supplied. A gateway that cached by default would change the
        # behaviour of every existing caller without any of them asking.
        self._cache = cache

    def _from_cache(
        self,
        completion: Completion,
        candidate: Resolution,
        span: ModelCallSpan,
        attempted: list[str],
    ) -> Consultation:
        """A hit, reported as one.

        `estimated_cost` is ZERO, not the cost the original call reported.
        `ResolutionRecord` feeds "what did this investigation spend", and
        replaying the original would make that total climb while no money moved
        - an investigation that answered its second identical question for free
        must be visibly cheaper, not invisibly the same.

        The span is marked too, so a trace does not show a model call that never
        happened taking zero milliseconds.
        """
        span.duration_ms = 0
        span.cached = True
        span.prompt_tokens = 0
        span.completion_tokens = 0
        span.cost = 0.0
        record = candidate.record.model_copy(
            update={
                "fallback_used": candidate.record.fallback_used or bool(attempted),
                "rejected": list(candidate.record.rejected) + attempted,
                "estimated_cost": 0.0,
            }
        )
        return Consultation(completion=completion, record=record, span=span)

    async def consult(
        self,
        requirements: ModelRequirements,
        *,
        prompt: str,
        requested_by: str,
        system: str | None = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> Consultation:
        """Resolve a model, call it, and return the completion with its record.

        Raises `Unresolvable` when nothing satisfies the requirements,
        `BudgetExceeded` when the only answer costs too much, and
        `ProviderError` when every candidate failed.
        """
        resolution = resolve(
            requirements,
            catalogue=self._catalogue,
            requested_by=requested_by,
            bindings=self._bindings,
        )
        attempted: list[str] = []
        last_error: ProviderError | None = None

        for candidate in self._chain(resolution, requirements):
            provider = self._providers.get(candidate.model.provider_id)
            if provider is None:
                attempted.append(f"{candidate.model.model_id} (no adapter for its provider)")
                continue

            span = span_for(
                requested_by=requested_by,
                model=candidate.model,
                matched_step=candidate.record.matched_step,
                prompt=prompt,
                fallback_used=bool(attempted),
                include_prompt=self._include_prompt,
            )
            key = CacheKey(
                model_id=candidate.model.model_id,
                prompt=prompt,
                system=system,
                token_ceiling=max_tokens,
                json_mode=json_mode,
            )
            if self._cache is not None:
                cached = self._cache.get(key)
                if isinstance(cached, Completion):
                    return self._from_cache(cached, candidate, span, attempted)

            started = time.perf_counter()
            try:
                completion = await provider.complete(
                    model_id=candidate.model.model_id,
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except ProviderError as failure:
                span.failed = True
                span.error = str(failure)
                span.duration_ms = int((time.perf_counter() - started) * 1000)
                attempted.append(f"{candidate.model.model_id} ({failure})")
                last_error = failure
                if not failure.retryable:
                    raise
                continue

            span.duration_ms = int((time.perf_counter() - started) * 1000)
            span.prompt_tokens = completion.prompt_tokens
            span.completion_tokens = completion.completion_tokens
            span.cost = completion.cost

            if not self._cost_guard(completion.cost, requirements.max_cost_per_call):
                raise BudgetExceeded(
                    f"{candidate.model.model_id} reported {completion.cost} against a "
                    f"ceiling of {requirements.max_cost_per_call} for {requested_by}. "
                    "Stopping rather than moving to a cheaper model, which would "
                    "produce worse output with no signal that anything changed."
                )

            record = candidate.record.model_copy(
                update={
                    "fallback_used": candidate.record.fallback_used or bool(attempted),
                    "rejected": list(candidate.record.rejected) + attempted,
                    "estimated_cost": completion.cost,
                }
            )
            if self._cache is not None:
                self._cache.put(key, completion)
            return Consultation(completion=completion, record=record, span=span)

        raise last_error or ProviderError(
            f"no provider answered for {requested_by}; tried {attempted or ['nothing']}",
            retryable=False,
        )

    def _chain(self, first: Resolution, requirements: ModelRequirements) -> list[Resolution]:
        """The first choice, then every other tier that also satisfies the requirements.

        Never widens the search. A chain that relaxed a declared capability under
        load would produce its worst output exactly when the system is already
        struggling.
        """
        chain = [first]
        seen = {first.model.model_id}
        for tier in Tier:
            model = self._catalogue.for_tier(tier)
            if model is None or model.model_id in seen:
                continue
            try:
                alternative = resolve(
                    requirements.model_copy(update={"tier": tier}),
                    catalogue=self._catalogue,
                    requested_by=first.record.requested_by,
                )
            except Unresolvable:
                continue
            if alternative.model.model_id not in seen:
                seen.add(alternative.model.model_id)
                chain.append(alternative)
        return chain
