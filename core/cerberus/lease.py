"""Short-lived leases, bound to one connector and one investigation.

Binding both is what makes a leaked lease worthless: it cannot be redeemed by a
different connector, nor carried into a different run, nor used after expiry.

Renewal: a lease auto-renews while its underlying grant is still valid and the
investigation is still running. If the grant expired or was revoked, renewal
fails with LeaseExpired - which the agent must surface as a Finding, never
swallow. The investigation then completes with a partial result rather than
dying or silently skipping the check.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement mint, renew and expiry, and define the LeaseExpired failure
