"""Grant matching: agent, target, action, scope, TTL.

Read and write are separate grants. A read grant never satisfies a write
request, mirroring the connector split between internal/readonly and
internal/write.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement grant lookup and matching
