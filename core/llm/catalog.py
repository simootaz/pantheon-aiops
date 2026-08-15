"""Configured providers: load, validate, enumerate.

Named catalog rather than registry on purpose - core/registry/ is the agent
registry, and two registry modules in one package tree invites import confusion
and mis-greps.

Holds ProviderConfig entries added from settings, resolves which models each
exposes (via its models endpoint or a manual list) and hands the right dialect
adapter to the gateway.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement provider load, validation and model enumeration
