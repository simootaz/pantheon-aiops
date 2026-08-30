"""Redeeming a lease for a credential. The only producer of plaintext.

**Connector-side only.** `tests/unit/test_credential_safety.py` forbids any
module under `agents/` from importing this, and that guard is the reason the
whole design holds: an agent handles `Lease` objects, which are safe to log and
worthless to steal, and never the values behind them.

WHAT IS CHECKED, AND WHY EACH ONE MATTERS ALONE
-------------------------------------------------
A lease names the one connector that may redeem it, the one run it belongs to,
and the moment it stops being worth anything. All three are checked here, at the
point of use, rather than trusted from whoever passed the lease in:

* **The connector.** A lease redeemed by a different one is a lease that leaked
  and was used. This is the check that makes "bound to one connector" true
  rather than descriptive.
* **The run.** A lease carried into a later investigation is permission granted
  for one question being spent on another.
* **The clock.** Checked here and not only at mint, because the interesting gap
  is between the two.

Checking at redemption rather than at hand-off is deliberate. A lease may sit in
an agent's context for the length of a run, and the only moment its validity
matters is the moment a secret would be produced.

THE PLAINTEXT IS RETURNED AND NOT STORED
------------------------------------------
It is not cached, not logged, and not attached to anything. A caller that keeps
it keeps it; nothing here helps. The audit entry records that a redemption
happened and against which `CredentialRef` - an identifier, never a value.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from uuid import UUID

from core.cerberus.audit.log import AuditLog
from core.cerberus.lease import LeaseBook
from core.cerberus.store.envelope import open_sealed
from core.cerberus.store.vault import CredentialNotFound, Vault
from core.contracts.credentials import AuditEvent, Lease


class RedemptionRefused(RuntimeError):
    """The lease cannot be redeemed, and the message says which check said no.

    One type, because every caller's next step is the same - do not proceed -
    but the message distinguishes them, since "this lease is for another
    connector" and "this lease expired" lead to very different conversations.
    """


def redeem(
    lease: Lease,
    *,
    vault: Vault,
    leases: LeaseBook,
    connector: str,
    investigation_id: UUID,
    master: bytes | None = None,
    audit: AuditLog | None = None,
) -> str:
    """Produce the plaintext credential, or refuse and say why.

    `connector` and `investigation_id` are what the CALLER is, supplied
    separately from the lease. Reading them off the lease would compare it
    against itself and check nothing - the whole point is that the lease's
    claims are tested against the context it is being used in.
    """
    if lease.connector != connector:
        _refuse(
            audit,
            lease,
            investigation_id,
            f"lease {lease.id} names connector {lease.connector!r} and is being "
            f"redeemed by {connector!r}. A lease redeemed by a different connector "
            "is one that leaked and was used.",
        )

    if lease.investigation_id != investigation_id:
        _refuse(
            audit,
            lease,
            investigation_id,
            f"lease {lease.id} belongs to investigation {lease.investigation_id} and "
            f"is being redeemed for {investigation_id}. Permission granted for one "
            "question is not permission for another.",
        )

    if not leases.live(lease):
        _refuse(
            audit,
            lease,
            investigation_id,
            f"lease {lease.id} expired at {lease.expires_at.isoformat()}. Renew it "
            "before redeeming, or surface the expiry as a Finding - a run that "
            "silently skipped a check is worse than one that reported it could not "
            "make it.",
        )

    try:
        sealed = vault.get(lease.credential_ref)
    except CredentialNotFound as missing:
        _refuse(audit, lease, investigation_id, str(missing))
        raise AssertionError("unreachable") from missing  # pragma: no cover

    plaintext = open_sealed(sealed, master=master)

    if audit is not None:
        # The event, the reference and the lease. Never the value - that is what
        # makes the trail safe to attach to an Investigation an agent can read.
        audit.append(
            AuditEvent.LEASE_USED,
            actor=connector,
            investigation_id=investigation_id,
            credential_ref=lease.credential_ref,
            action=lease.action,
            lease_id=lease.id,
            detail=f"redeemed {lease.credential_ref.name} for {connector}",
        )

    return plaintext


def _refuse(audit: AuditLog | None, lease: Lease, investigation_id: UUID, why: str) -> None:
    """Record the refusal, then raise it.

    Recorded first. A refusal that raised without a trail would leave "a
    connector tried to redeem a lease it did not hold" in an exception message
    and nowhere else, and that is precisely the event somebody would want to
    find later.
    """
    if audit is not None:
        audit.append(
            AuditEvent.DENIED,
            actor=lease.connector,
            investigation_id=investigation_id,
            credential_ref=lease.credential_ref,
            action=lease.action,
            lease_id=lease.id,
            detail=why,
        )
    raise RedemptionRefused(why)
