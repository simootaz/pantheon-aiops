"""Head one: custody.

Encrypted storage for every credential type. Holds plaintext at rest and in
memory, so it sits behind the same import boundary as redemption.py - agents
must not import anything under this package.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - expose the vault interface
