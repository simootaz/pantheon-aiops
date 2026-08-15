"""Rotate a credential in place, retaining the previous version.

Old-version retention is not politeness - it is what stops a rotation breaking
an investigation that already holds a live lease. The previous version stays
redeemable until the last lease issued against it expires, then is destroyed.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement rotate(), old-version retention and expiry-driven destruction
