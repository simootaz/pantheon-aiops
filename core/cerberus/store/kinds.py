"""Per-type handling: database, SSH, kubeconfig, HTTP auth, cloud key, TLS, key-value.

Each type knows how to validate its own shape and how to hand itself to a
connector at redemption time. None of them is a contract model.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement per-type validation and connector handoff
