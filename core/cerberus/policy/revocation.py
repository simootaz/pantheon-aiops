"""Revocation, including break-glass.

Three scopes:

  - revoke one grant
  - revoke every grant held by one agent
  - break-glass: revoke everything and invalidate every live lease immediately

Break-glass is the 3am control. When an agent is misbehaving there is no time to
reason about which grant matters, so the only useful action is to stop all of
them at once - and live leases must die with the grants, or revocation is
advisory for as long as the longest TTL.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement the three revocation scopes and immediate lease invalidation
