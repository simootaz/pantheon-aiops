"""Delphi entrypoint - the only module agents call.

Takes ModelRequirements and a prompt, resolves a model, invokes the right
dialect adapter, records a ResolutionRecord on the Investigation and returns the
completion.

Agents pass requirements, never a model name. An agent that names a model is a
bug, not a shortcut.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement consult(): resolve, dispatch, record
