"""Master key resolution: environment, Sealed Secret, or external KMS.

The master key is never written to disk in plaintext and never included
unencrypted in a backup - deploy/backup/ inherits this constraint from
docs/adr/0001-object-storage-minio.md.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement the resolution chain and a KMS-backed provider
