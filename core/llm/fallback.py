"""The fallback chain: what Delphi tries next when a provider fails.

THE CHAIN NEVER WIDENS THE SEARCH
-----------------------------------
Every candidate after the first must satisfy the SAME requirements. Not a
relaxed version of them, not "close enough under load".

A chain that dropped a declared capability when the first choice was
unreachable would produce its worst output at exactly the moment the system is
already struggling - and nothing in the result would say so. The agent asked for
`JSON_MODE`, got prose, and reports a parse error about a model it never chose.
Failing is the better outcome: `Unresolvable` names what was wanted and what was
rejected, and an operator can act on it.

WHY THIS IS A MODULE AND NOT A METHOD
---------------------------------------
It was a method on `Delphi`, alongside resolution, cost, caching, tracing and
the retry loop. Pulling it out is not tidying: the "never widens" rule is the
one an optimisation would quietly break, and a rule buried in the fifth
responsibility of a class is a rule nobody reviews.

Cost is NOT decided here. `core/guardrails/budget.within_cost_ceiling` owns
that - Delphi supplies the price, guardrails make the decision, and budget
policy stays in one place.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from core.contracts.llm import ModelRequirements, Tier
from core.llm.catalog import Catalogue
from core.llm.resolver import Resolution, Unresolvable, resolve


def chain(
    first: Resolution, requirements: ModelRequirements, *, catalogue: Catalogue
) -> list[Resolution]:
    """The first choice, then every other tier that ALSO satisfies the requirements.

    Ordered: the resolved choice leads, and the remaining tiers follow in their
    declared order. Deliberately not sorted by price or latency - a cheaper
    model that satisfies the requirements is still a different model, and
    reordering the chain by cost would make the fallback path silently prefer
    something the tier binding did not choose.

    Deduplicated by model id, because two tiers pointing at the same model is a
    normal configuration and retrying it twice is one wasted call and one
    misleading `rejected` entry.

    ONE dedup check, not two. There were two - one before the resolve and one
    after - and each was individually sufficient, so removing either changed
    nothing and no test could tell them apart. Two guards where one suffices
    means neither is testable, which is worse than the wasted call the second
    one saved.
    """
    ordered = [first]
    seen = {first.model.model_id}

    for tier in Tier:
        candidate = catalogue.for_tier(tier)
        if candidate is None or candidate.model_id in seen:
            continue
        try:
            # Re-resolved rather than taken from the tier binding directly. The
            # binding says which model that tier means; only the resolver says
            # whether it satisfies the requirements, and skipping it here is how
            # the chain would start widening without anyone editing this rule.
            alternative = resolve(
                requirements.model_copy(update={"tier": tier}),
                catalogue=catalogue,
                requested_by=first.record.requested_by,
            )
        except Unresolvable:
            continue

        seen.add(alternative.model.model_id)
        ordered.append(alternative)

    return ordered
