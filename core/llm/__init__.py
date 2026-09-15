"""Delphi - the LLM gateway.

Agents consult the Oracle; they never choose a model. Delphi sits beside the
orchestrator as infrastructure: it is not an agent, has no roster entry and
ships no manifest.yaml.

Public surface is `consult()` for a completion and `resolve()` when a caller
only needs to know which model would be chosen.

See docs/adr/0004-llm-provider-abstraction.md.

Phase: 2 - Orchestrator & Investigation Flow
"""

# No re-export. Callers import `core.llm.gateway.Delphi` and
# `core.llm.resolver.resolve` directly; a second name for the same object is one
# more place to keep in step - see agents/anomaly/__init__.py for the same call.
