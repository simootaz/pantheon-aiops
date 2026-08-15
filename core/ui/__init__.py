"""A2UI surface construction.

Pantheon assembles surfaces here; agents describe intent, and this package turns
that into components drawn strictly from the allowlist in
core.contracts.ui.A2UIComponentType.

Identity fields on A2UISurface are set by the orchestrator, never by an agent.

ALLOWED IMPORT SURFACE
----------------------
Code under ``agents/`` may import the surface builders, but **not**:

    core.ui.artifact_resolution  - turns an ArtifactRef into a fetchable signed
                                   URL. An agent that could resolve could also
                                   read the result, which is the exfiltration
                                   path ArtifactRef exists to close.

The same boundary as ``core.cerberus.redemption``, for the same reason: the
agent holds a reference, the server holds the capability. Enforced at the import
graph by tests/unit/test_credential_safety.py.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - expose the surface builders
