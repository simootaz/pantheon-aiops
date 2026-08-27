"""The four-step resolution cascade.

per-task override -> per-agent binding -> tier default -> global default.

The first binding that *satisfies the declared requirements* wins; a binding
that does not is skipped rather than used. An explicit override that cannot
satisfy them is an error, not a silent downgrade - otherwise an override becomes
a way to quietly break an agent.

WHY REJECTIONS ARE RECORDED
----------------------------
`ResolutionRecord.rejected` carries every candidate that was considered and
passed over, with the reason. A record showing only the winner cannot answer the
question actually asked after a bad run - "why did it pick that one?" - and the
answer is usually in what it declined.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from core.contracts.llm import (
    ModelDescriptor,
    ModelRequirements,
    ResolutionRecord,
    ResolutionStep,
    Tier,
)
from core.llm.catalog import Catalogue, satisfies


class Unresolvable(RuntimeError):
    """Nothing configured satisfies the declared requirements.

    A hard stop, deliberately. An agent that declared `TOOL_USE` and silently
    received a model without it does not fail - it produces confident nonsense,
    which costs far more to debug than an error at the point of resolution.
    """


class OverrideRejected(Unresolvable):
    """An explicit override cannot satisfy the requirements.

    A distinct type from `Unresolvable` because the fixes differ: this one means
    an operator asked for something specific and wrong, and telling them "no
    model matched" would send them to configure more models when the problem is
    the pin they set.
    """


@dataclass(frozen=True)
class Bindings:
    """Standing policy, from settings or an operator.

    Separate from the catalogue because a binding is a *preference* and the
    catalogue is *what exists*. Merging them would make "Hermes prefers the
    frontier tier" indistinguishable from "the frontier tier is all there is".
    """

    #: One run, pinned by an operator. The narrowest, most deliberate signal.
    task_override: str | None = None
    #: Standing per-agent policy, e.g. {"hermes": "qwen2.5:32b"}.
    per_agent: dict[str, str] | None = None
    #: Used when the agent's own tier yields nothing.
    global_default_tier: Tier = Tier.BALANCED


@dataclass(frozen=True)
class Resolution:
    """What was chosen, and the record explaining why."""

    model: ModelDescriptor
    record: ResolutionRecord


def resolve(
    requirements: ModelRequirements,
    *,
    catalogue: Catalogue,
    requested_by: str,
    bindings: Bindings | None = None,
) -> Resolution:
    """First binding that satisfies the requirements, in cascade order."""
    policy = bindings or Bindings()
    rejected: list[str] = []

    override = _override(requirements, catalogue, policy, rejected)
    if override is not None:
        return _resolution(
            requirements, requested_by, override, ResolutionStep.TASK_OVERRIDE, rejected
        )

    agent_binding = _agent_binding(requirements, catalogue, policy, requested_by, rejected)
    if agent_binding is not None:
        return _resolution(
            requirements, requested_by, agent_binding, ResolutionStep.AGENT_BINDING, rejected
        )

    tier_default = _tier(requirements, catalogue, requirements.tier, rejected)
    if tier_default is not None:
        return _resolution(
            requirements, requested_by, tier_default, ResolutionStep.TIER_DEFAULT, rejected
        )

    fallback = _tier(requirements, catalogue, policy.global_default_tier, rejected)
    if fallback is not None:
        return _resolution(
            requirements, requested_by, fallback, ResolutionStep.GLOBAL_DEFAULT, rejected
        )

    if not catalogue.models:
        raise Unresolvable(
            f"{requested_by} asked for a model and nothing was configured at all. "
            "The catalogue is empty, which is a deployment problem rather than a "
            "requirements one - no candidate was rejected because none existed."
        )

    raise Unresolvable(
        f"nothing configured satisfies {requested_by}'s requirements "
        f"(tier={requirements.tier.value}, capabilities="
        f"{[c.value for c in requirements.capabilities]}, min_context={requirements.min_context}). "
        f"Considered and rejected: {rejected}. "
        "This is a hard stop rather than a downgrade: a model missing a declared "
        "capability produces confident nonsense instead of an error."
    )


def _override(
    requirements: ModelRequirements,
    catalogue: Catalogue,
    policy: Bindings,
    rejected: list[str],
) -> ModelDescriptor | None:
    """An operator's pin. Wrong is an error, not a downgrade."""
    if not policy.task_override:
        return None

    model = catalogue.models.get(policy.task_override)
    if model is None:
        raise OverrideRejected(
            f"task override {policy.task_override!r} is not in the catalogue. "
            f"Configured: {sorted(catalogue.models)}"
        )
    if not _fits(model, requirements):
        raise OverrideRejected(
            f"task override {policy.task_override!r} does not satisfy the declared "
            f"requirements (capabilities={[c.value for c in requirements.capabilities]}, "
            f"min_context={requirements.min_context}). An override that silently "
            "downgraded would be a way to quietly break an agent."
        )
    rejected.clear()
    return model


def _agent_binding(
    requirements: ModelRequirements,
    catalogue: Catalogue,
    policy: Bindings,
    requested_by: str,
    rejected: list[str],
) -> ModelDescriptor | None:
    """Standing policy. Skipped when it does not fit, not enforced."""
    bound = (policy.per_agent or {}).get(requested_by)
    if not bound:
        return None

    model = catalogue.models.get(bound)
    if model is None:
        rejected.append(f"{bound} (bound to {requested_by}, but not in the catalogue)")
        return None
    if not _fits(model, requirements):
        rejected.append(f"{bound} (bound to {requested_by}, but does not satisfy requirements)")
        return None
    return model


def _tier(
    requirements: ModelRequirements,
    catalogue: Catalogue,
    tier: Tier,
    rejected: list[str],
) -> ModelDescriptor | None:
    model = catalogue.for_tier(tier)
    if model is None:
        _reject(rejected, f"tier {tier.value} (no model configured)")
        return None
    if not _fits(model, requirements):
        _reject(rejected, f"{model.model_id} (tier {tier.value}, does not satisfy requirements)")
        return None
    return model


def _reject(rejected: list[str], reason: str) -> None:
    """Record a rejection once.

    The agent's own tier and the global default are frequently the same tier, so
    an undeduplicated list reports the identical candidate twice - which reads
    as two separate considerations and makes the record say something that did
    not happen. Order is preserved because it is the order they were tried in.
    """
    if reason not in rejected:
        rejected.append(reason)


def _fits(model: ModelDescriptor, requirements: ModelRequirements) -> bool:
    return satisfies(
        model,
        required=list(requirements.capabilities),
        min_context=requirements.min_context,
    )


def _resolution(
    requirements: ModelRequirements,
    requested_by: str,
    model: ModelDescriptor,
    step: ResolutionStep,
    rejected: list[str],
) -> Resolution:
    return Resolution(
        model=model,
        record=ResolutionRecord(
            id=uuid4(),
            requested_by=requested_by,
            requirements=requirements,
            matched_step=step,
            chosen=model,
            rejected=list(rejected),
            fallback_used=step is ResolutionStep.GLOBAL_DEFAULT,
            estimated_cost=None,
            resolved_at=datetime.now(UTC),
        ),
    )
