"""User-defined providers, added from settings with no code.

This is what makes 'any provider' real rather than aspirational. An operator
supplies base_url, dialect, auth mode, and either a models endpoint to enumerate
or a manual model list - and the provider works.

Without this, 'any provider' would mean 'any provider we shipped an adapter
for', which is a different and much smaller claim.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 5 - extend settings-defined providers to the remaining dialects.
#
# THE CAPABILITY THIS FILE DESCRIBES HAS LANDED, ELSEWHERE. An operator adds a
# provider through `POST /providers` with a base URL, dialect, auth mode and
# either a models endpoint or a manual list, and it works - see
# api/routers/providers.py and core/store/providers.py.
#
# There is no code to write here for `chat_completions`: `ChatCompletionsProvider`
# is constructed directly from the stored `ProviderConfig`, so a second module
# doing the same thing would be a second path to keep in step.
#
# What remains is the other three dialects, which is ADR 0004 Phase 5 - and the
# door refuses them today rather than storing a provider that looks configured
# and fails when an agent needs it.
