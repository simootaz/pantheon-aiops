"""Fallback chain, budget guard and hard stop.

On failure Delphi tries the next candidate that satisfies the requirements, then
checks cost, then stops.

Cost enforcement delegates to core.guardrails.budget: Delphi supplies the price,
guardrails make the decision. Policy lives in one place.

Hard stop beats silent downgrade. An agent that declared TOOL_USE and silently
received a model without it does not fail - it produces confident nonsense,
which is far more expensive to debug than an error.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement the chain, then delegate the cost decision to core.guardrails.budget
