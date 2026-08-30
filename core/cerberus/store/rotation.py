"""Rotate a credential in place, retaining the previous version.

Old-version retention is not politeness - it is what stops a rotation breaking
an investigation that already holds a live lease. The previous version stays
redeemable until the last lease issued against it expires, then is destroyed.

WHICH VERSION A LEASE GETS IS DECIDED BY WHEN IT WAS ISSUED
-------------------------------------------------------------
Not by a flag, not by a version number the caller passes. A lease issued before
the rotation gets the value that was current when it was issued; one issued
after gets the new value.

That is the only rule that cannot be got wrong by a caller. A version parameter
would put the decision in the hands of whoever calls `redeem`, and the one
caller that forgot would get the new secret for an old lease and fail
authentication against a system mid-rotation - which reads as a rotation that
did not propagate.

THE RETENTION WINDOW IS COMPUTED, NOT CONFIGURED
--------------------------------------------------
At rotation, the latest expiry among the live leases for that credential is
already known. That moment is exactly when the old version stops being
reachable, so it is the retention window - no setting, and nothing to tune.

If no lease is live, the old version is retired immediately. Keeping it "just
in case" would keep a superseded secret redeemable for a window nobody chose.

EXPIRY IS ANSWERED ON READ
----------------------------
The same choice as the lease book, the approval gate and the capability matrix.
`purge` exists to reclaim memory and changes no answer: a retired version past
its window is unreachable whether or not anything swept it, so a system under
scheduler pressure answers the same as an idle one.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from core.cerberus.audit.log import AuditLog
from core.cerberus.lease import LeaseBook
from core.cerberus.store.vault import Vault
from core.contracts.credentials import AuditEvent, CredentialAction, CredentialRef


@dataclass(frozen=True)
class Rotation:
    """What a rotation did, and how long the old value stays reachable."""

    ref: CredentialRef
    at: datetime
    #: When the previous version stops being redeemable. Equal to `at` when no
    #: lease was live, which retires it immediately.
    retained_until: datetime
    #: Live leases that will still resolve to the previous value.
    leases_carried: int

    @property
    def retained(self) -> bool:
        return self.leases_carried > 0

    def __str__(self) -> str:
        if not self.retained:
            return f"{self.ref.name} rotated at {self.at.isoformat()}; no lease was live"
        return (
            f"{self.ref.name} rotated at {self.at.isoformat()}; {self.leases_carried} "
            f"live leases keep the previous value until {self.retained_until.isoformat()}"
        )


def rotate(
    ref: CredentialRef,
    new_value: str,
    *,
    vault: Vault,
    leases: LeaseBook,
    by: str = "system",
    audit: AuditLog | None = None,
    now: datetime | None = None,
) -> Rotation:
    """Replace a credential, keeping the previous value redeemable for live leases.

    A malformed new value changes nothing. `Vault.put` validates, and
    `supersede` stores the new value BEFORE recording the retired one - so a
    refusal leaves both untouched, and the credential is never left rotated to
    something unusable with the old value already superseded.

    That check is not repeated here. It was, and removing it changed no test:
    two guards doing one job, neither testable alone. The property is asserted
    instead of the call, by `test_a_rotation_to_a_malformed_value_changes_nothing`.
    """
    at = now or datetime.now(tz=UTC)

    carried = [lease for lease in leases.live_leases() if lease.credential_ref.id == ref.id]
    retained_until = max((lease.expires_at for lease in carried), default=at)

    vault.supersede(ref, new_value, superseded_at=at, retained_until=retained_until)

    if audit is not None:
        audit.append(
            AuditEvent.ROTATED,
            actor=by,
            credential_ref=ref,
            action=CredentialAction.NOT_APPLICABLE,
            detail=(
                f"rotated {ref.name}; {len(carried)} live leases keep the previous "
                f"value until {retained_until.isoformat()}"
            ),
        )

    return Rotation(ref=ref, at=at, retained_until=retained_until, leases_carried=len(carried))


def purge(vault: Vault, *, now: datetime | None = None) -> int:
    """Destroy retired versions whose window has passed. Returns how many.

    Reclaims memory and changes no answer - a retired version past its window
    is already unreachable through `Vault.version_for`. Calling this never
    makes a redemption fail that would otherwise have succeeded, which is what
    makes it safe to run on a timer.
    """
    return vault.purge_retired(now=now or datetime.now(tz=UTC))
