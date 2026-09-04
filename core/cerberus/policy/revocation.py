"""Revocation, including break-glass.

Three scopes:

  - revoke one grant
  - revoke every grant held by one agent
  - break-glass: revoke everything and invalidate every live lease immediately

Break-glass is the 3am control. When an agent is misbehaving there is no time to
reason about which grant matters, so the only useful action is to stop all of
them at once - and live leases must die with the grants, or revocation is
advisory for as long as the longest TTL.

WHY THE LEASES ARE THE POINT
------------------------------
Revoking a grant stops the NEXT lease. It does nothing to the leases already
minted, and a lease is redeemable for its whole TTL without consulting the
grant again - by design, because redemption must not depend on a policy lookup
being reachable.

So a revocation that touched only grants would be a revocation that takes
effect in five minutes. That is defensible for one grant and indefensible for
break-glass, which is used precisely when five minutes is the whole problem.

Every scope here kills the leases too. The narrow ones only kill the leases
they granted; break-glass kills all of them, including any minted from a grant
this book never saw.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from core.cerberus.audit.log import AuditLog
from core.cerberus.lease import LeaseBook
from core.cerberus.policy.grants import GrantBook
from core.contracts.credentials import AuditEvent, CredentialAction


@dataclass(frozen=True)
class Revocation:
    """What a revocation actually stopped.

    Both numbers, separately. "revoked 3" cannot answer the question anybody
    asks after pulling the handle - three grants with eleven live leases still
    redeemable is not a system that has stopped.
    """

    grants: int
    leases: int
    at: datetime

    def __str__(self) -> str:
        return f"{self.grants} grants and {self.leases} leases, at {self.at.isoformat()}"


def revoke_grant(
    grant_id: UUID,
    *,
    grants: GrantBook,
    leases: LeaseBook,
    by: str,
    audit: AuditLog | None = None,
    now: datetime | None = None,
) -> Revocation:
    """Revoke one grant and every live lease minted from it."""
    at = now or datetime.now(tz=UTC)
    grant = grants.get(grant_id)
    revoked = grants.mark_revoked(grant_id, at=at)
    killed = leases.revoke_from_grant(grant_id) if revoked else 0

    if audit is not None and revoked:
        audit.append(
            AuditEvent.GRANT_REVOKED,
            actor=by,
            credential_ref=grant.credential_ref if grant is not None else None,
            action=grant.action if grant is not None else CredentialAction.NOT_APPLICABLE,
            detail=f"revoked grant {grant_id} and {killed} live leases",
        )
    return Revocation(grants=1 if revoked else 0, leases=killed, at=at)


def revoke_agent(
    agent: str,
    *,
    grants: GrantBook,
    leases: LeaseBook,
    by: str,
    audit: AuditLog | None = None,
    now: datetime | None = None,
) -> Revocation:
    """Revoke every grant one agent holds, and every live lease behind them.

    Scoped to the agent rather than to the credential, because the reason to
    reach for this is a misbehaving agent - and asking which of its grants to
    keep is a question with no good answer while it is still running.
    """
    at = now or datetime.now(tz=UTC)
    stopped = 0
    killed = 0
    for grant in grants.held_by(agent):
        if grants.mark_revoked(grant.id, at=at):
            stopped += 1
            killed += leases.revoke_from_grant(grant.id)

    if audit is not None and stopped:
        audit.append(
            AuditEvent.GRANT_REVOKED,
            actor=by,
            detail=f"revoked every grant held by {agent}: {stopped} grants, {killed} leases",
        )
    return Revocation(grants=stopped, leases=killed, at=at)


def break_glass(
    *,
    grants: GrantBook,
    leases: LeaseBook,
    by: str,
    reason: str,
    audit: AuditLog | None = None,
    now: datetime | None = None,
) -> Revocation:
    """Stop everything. Every grant revoked, every live lease dead, now.

    `reason` is required and is not decoration: this is the one control whose
    use is itself an incident, and the trail is where somebody reconstructs
    what was happening. It is recorded even when nothing was revoked, because
    pulling the handle on an already-quiet system is still an event.

    Every lease is killed, not only those from grants in this book. A lease
    minted before a restart, or from a grant since deleted, is exactly the one
    break-glass exists to catch.
    """
    at = now or datetime.now(tz=UTC)
    stopped = sum(1 for grant in grants.all() if grants.mark_revoked(grant.id, at=at))
    killed = leases.revoke_all()

    if audit is not None:
        audit.append(
            AuditEvent.BREAK_GLASS,
            actor=by,
            detail=f"break-glass by {by}: {reason}. Stopped {stopped} grants, {killed} leases",
        )
    return Revocation(grants=stopped, leases=killed, at=at)
