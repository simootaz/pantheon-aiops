"""Connector-side redemption: Lease -> plaintext.

THE ONLY MODULE THAT PRODUCES PLAINTEXT.

Importable by connectors. NOT importable by agents - tests/unit/
test_credential_safety.py fails the build if anything under agents/ imports it.

Plaintext returned here has no contract representation and never enters
core.contracts, so it cannot be serialised into an Evidence, a Finding, an
Investigation or a WebSocket frame.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement redeem(): verify connector, investigation and expiry, then fetch
