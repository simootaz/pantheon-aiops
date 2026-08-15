"""Provider credentials: encrypted at rest, redacted everywhere else.

Keys are never stored in plaintext config, never written to logs, never attached
to a ResolutionRecord, and redacted in traces by core.llm.tracing.

ProviderConfig carries only a `secret_ref` naming the credential; the credential
itself never leaves this module.

Supplied per environment: Compose from env vars, Helm from `existingSecret`,
in-cluster from Sealed Secrets (deploy/security/sealed-secrets/).

A key that reaches an Investigation record is a security bug, not a cosmetic
one - Investigations are persisted, exported in reports and rendered in the
dashboard.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement encrypted storage, retrieval by secret_ref and redaction helpers
