"""Short-lived leases, bound to one connector and one investigation.

Binding both is what makes a leaked lease worthless: it cannot be redeemed by a
different connector, nor carried into a different run, nor used after expiry.

A LEASE IS NOT A CREDENTIAL
-----------------------------
It is permission to have one handed to a named connector, later. Nothing here
touches a secret and nothing here can produce one - `core/cerberus/redemption.py`
is the only module that yields plaintext, and it takes a lease as its input.

That separation is the point of the whole subsystem. An agent holds a `Lease`,
which is safe to log, safe to put on an Investigation, and useless to anyone who
steals it.

RENEWAL, AND WHAT IT REFUSES
------------------------------
A lease auto-renews while its grant is still valid and the run is still live.
When the grant expired or was revoked, renewal fails with `LeaseExpired` - which
the agent must surface as a Finding rather than swallow, so the investigation
completes visibly partial instead of quietly short.

Renewal never extends past the grant. A lease that outlived its grant would be
permission nobody granted, and the renewal is exactly where that would happen
without anyone deciding to.

EXPIRY IS ANSWERED ON READ
----------------------------
The same choice as the approval gate and the capability matrix, for the same
reason: a background sweep makes "expired" depend on whether the sweep ran, and
a credential system that answers differently under scheduler pressure is not one
anybody can reason about.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from core.contracts.credentials import CredentialAction, Grant, Lease, PermissionMode

#: How long a lease lives before it must be renewed. Short: a lease is held for
#: the length of one connector call, not one investigation, and the window in
#: which a stolen one is worth anything is exactly this long.
DEFAULT_TTL = timedelta(minutes=5)

#: Renewals allowed on one lease. A bound rather than unlimited, because an
#: agent looping on a renewal it never uses is indistinguishable from one making
#: progress, and both keep a credential reachable indefinitely.
MAX_RENEWALS = 12


class LeaseExpired(RuntimeError):
    """The lease cannot be renewed, and cannot be redeemed again.

    Raised rather than returned as a falsy lease. A caller that forgot to check
    a return value would carry on with an expired lease and fail at redemption
    with a message about a credential, which reads as a vault problem rather
    than as an expiry.
    """


class LeaseNotRenewable(RuntimeError):
    """The lease was minted without renewal, or has renewed as often as allowed."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass
class LeaseBook:
    """Every lease this process has minted, and what it is allowed to become.

    In-process, like the approval gate. A lease is short-lived by design, so the
    thing persistence would buy - a lease surviving a restart - is a lease that
    should have expired instead.
    """

    ttl: timedelta = DEFAULT_TTL
    clock: Callable[[], datetime] = field(default_factory=lambda: _now)
    _leases: dict[UUID, Lease] = field(default_factory=dict)
    _grants: dict[UUID, Grant] = field(default_factory=dict)

    def mint(
        self,
        grant: Grant,
        *,
        investigation_id: UUID,
        connector: str,
        action: CredentialAction,
        request_id: UUID,
        renewable: bool = True,
    ) -> Lease:
        """Issue a lease against a live grant, for one connector and one run.

        The grant is checked first. Minting from an expired or revoked grant
        would create permission nobody currently holds - and the lease would
        look identical to a valid one for its whole life.
        """
        now = self.clock()
        self._refuse_dead_grant(grant, now=now)

        if action is not grant.action:
            raise LeaseExpired(
                f"grant {grant.id} permits {grant.action.value}, not {action.value}. "
                "A lease cannot widen what was granted."
            )

        if (
            grant.mode is PermissionMode.ALLOW_FOR_INVESTIGATION
            and grant.investigation_id != investigation_id
        ):
            raise LeaseExpired(
                f"grant {grant.id} is scoped to investigation {grant.investigation_id} "
                f"and this lease is for {investigation_id}. A grant given for one run "
                "does not carry into another - that is the whole of what the mode means."
            )

        lease = Lease(
            id=uuid4(),
            request_id=request_id,
            investigation_id=investigation_id,
            connector=connector,
            credential_ref=grant.credential_ref,
            action=action,
            issued_at=now,
            # Never past the grant. A lease that outlived its grant would be
            # permission nobody gave, arrived at by arithmetic.
            expires_at=_bounded(now + self.ttl, grant.expires_at),
            renewable=renewable,
        )
        self._leases[lease.id] = lease
        self._grants[lease.id] = grant
        return lease

    def live(self, lease: Lease) -> bool:
        """Whether this lease is still usable, judged now rather than on a timer."""
        return self.clock() < lease.expires_at

    def renew(self, lease: Lease) -> Lease:
        """Extend a live lease, or refuse and say which reason.

        Five ways this fails and they are not interchangeable: the lease is
        unknown, it has already expired or been revoked, it was minted
        non-renewable, it has renewed as often as allowed, or the grant behind
        it is gone. The last is the one an agent must surface as a Finding.

        The expiry check is not redundant with the grant check. `revoke` works
        by expiring the LEASE while the grant stays perfectly alive, so without
        it a revocation was undone by the next renewal - which is what the test
        for it found.
        """
        known = self._leases.get(lease.id)
        if known is None:
            raise LeaseExpired(f"lease {lease.id} was not minted here and cannot be renewed")

        now = self.clock()

        # The GRANT first. When both are dead the grant is the actionable fact -
        # "your permission was withdrawn" is what an agent surfaces as a Finding,
        # while a lease past its five-minute TTL is the ordinary case renewal
        # exists to handle and says nothing anyone needs to act on.
        grant = self._grants[known.id]
        self._refuse_dead_grant(grant, now=now)

        if now >= known.expires_at:
            raise LeaseExpired(
                f"lease {known.id} expired at {known.expires_at.isoformat()} while its "
                "grant is still live, so it was revoked. Renewal extends a lease; it "
                "does not resurrect one - and `revoke` works by expiring, so without "
                "this check a revocation is undone by the next renewal."
            )
        if not known.renewable:
            raise LeaseNotRenewable(f"lease {known.id} was minted non-renewable")
        if known.renewed_count >= MAX_RENEWALS:
            raise LeaseNotRenewable(
                f"lease {known.id} has renewed {known.renewed_count} times, the limit "
                f"is {MAX_RENEWALS}. An agent renewing without progressing keeps a "
                "credential reachable indefinitely."
            )

        renewed = known.model_copy(
            update={
                "expires_at": _bounded(now + self.ttl, grant.expires_at),
                "renewed_count": known.renewed_count + 1,
            }
        )
        self._leases[renewed.id] = renewed
        return renewed

    def revoke(self, lease_id: UUID) -> bool:
        """End a lease immediately. Returns whether there was one to end.

        Expiring rather than deleting: a lease that vanished would make a later
        redemption fail with "unknown lease", which reads as a bug in whoever
        held it rather than as a revocation somebody performed.
        """
        known = self._leases.get(lease_id)
        if known is None:
            return False
        self._leases[lease_id] = known.model_copy(update={"expires_at": self.clock()})
        return True

    def _refuse_dead_grant(self, grant: Grant, *, now: datetime) -> None:
        """The one check both minting and renewal share."""
        if grant.mode is PermissionMode.DENY:
            raise LeaseExpired(
                f"grant {grant.id} is a DENY. Minting against one would turn a "
                "recorded refusal into permission."
            )
        if grant.revoked_at is not None:
            raise LeaseExpired(
                f"grant {grant.id} was revoked at {grant.revoked_at.isoformat()}; a lease "
                "against it would be permission nobody currently holds"
            )
        if grant.expires_at is not None and now >= grant.expires_at:
            raise LeaseExpired(
                f"grant {grant.id} expired at {grant.expires_at.isoformat()}. Renewal "
                "never extends past the grant - an agent must surface this as a Finding "
                "rather than swallow it, so the run completes visibly partial."
            )


def _bounded(proposed: datetime, ceiling: datetime | None) -> datetime:
    """A lease expiry, never past the grant's own.

    `Grant.expires_at` is optional - only ALLOW_UNTIL sets one - so an
    unbounded grant leaves the lease's own TTL as the only limit. That is
    correct and worth stating: the short TTL is what bounds a lease under a
    grant that names no end, and it is why the TTL is minutes rather than hours.
    """
    return proposed if ceiling is None else min(proposed, ceiling)
