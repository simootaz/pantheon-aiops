"""User-defined providers, added from settings with no code.

This is what makes 'any provider' real rather than aspirational. An operator
supplies base_url, dialect, auth mode, and either a models endpoint to enumerate
or a manual model list - and the provider works.

Without this, 'any provider' would mean 'any provider we shipped an adapter
for', which is a different and much smaller claim.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement settings-defined providers on top of the four dialects
