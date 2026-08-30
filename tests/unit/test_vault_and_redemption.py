"""The vault and the one path out of it.

Every test here is a way a credential could escape, or a way a lease could be
worth more than it should be. The vault holds ciphertext and has no plaintext
getter; redemption is the only producer, and it checks the lease against the
context it is being used in rather than against itself.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.cerberus.audit.log import AuditLog
from core.cerberus.lease import LeaseBook
from core.cerberus.redemption import RedemptionRefused, redeem
from core.cerberus.store.envelope import DecryptionFailed, open_sealed
from core.cerberus.store.vault import CredentialNotFound, Vault
from core.contracts.credentials import (
    AuditEvent,
    CredentialAction,
    CredentialRef,
    CredentialType,
    Grant,
    PermissionMode,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
RUN = uuid4()
MASTER = os.urandom(32)
SECRET = "postgres://user:hunter2@db:5432/prod"


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _ref(name: str = "prod-postgres") -> CredentialRef:
    return CredentialRef(id=str(uuid4()), name=name, type=CredentialType.DATABASE)


def _grant(ref: CredentialRef) -> Grant:
    return Grant(
        id=uuid4(),
        agent="argus",
        credential_ref=ref,
        action=CredentialAction.READ,
        mode=PermissionMode.ALLOW_UNTIL,
        expires_at=NOW + timedelta(hours=1),
        granted_by="alex",
        granted_at=NOW,
    )


def _stocked() -> tuple[Vault, LeaseBook, _Ticker, CredentialRef]:
    ref = _ref()
    vault = Vault(master=MASTER)
    vault.put(ref, SECRET)
    clock = _Ticker()
    return vault, LeaseBook(clock=clock), clock, ref


def _lease(book: LeaseBook, ref: CredentialRef, *, connector: str = "postgres"):  # type: ignore[no-untyped-def]
    return book.mint(
        _grant(ref),
        investigation_id=RUN,
        connector=connector,
        action=CredentialAction.READ,
        request_id=uuid4(),
    )


# --- the vault holds ciphertext and nothing else -------------------------------------


def test_a_stored_credential_is_not_in_the_vault_in_the_clear() -> None:
    """The property everything else rests on. A vault dumped from memory must
    yield ciphertext."""
    vault, _, _, ref = _stocked()

    rendered = json.dumps(vault.get(ref).as_dict())

    assert SECRET not in rendered
    assert "hunter2" not in rendered


def test_the_vault_has_no_way_to_hand_back_plaintext() -> None:
    """Asserted on the surface. A convenience getter here would put a decrypt
    one import away from an agent, and `core.cerberus.store` is exactly what
    agents are forbidden to import."""
    forbidden = [
        name
        for name in dir(Vault)
        if any(word in name.lower() for word in ("plaintext", "decrypt", "reveal", "open"))
    ]

    assert not forbidden, f"Vault exposes {forbidden}; redemption is the only producer"


def test_listing_returns_references_and_never_values() -> None:
    vault, _, _, ref = _stocked()

    rendered = json.dumps([entry.model_dump(mode="json") for entry in vault.list()])

    assert ref.name in rendered
    assert SECRET not in rendered


def test_an_empty_credential_is_refused_rather_than_stored() -> None:
    """It authenticates as nothing and fails as though the credential were
    wrong, which sends whoever debugs it to the provider."""
    vault = Vault(master=MASTER)

    with pytest.raises(ValueError, match="empty credential"):
        vault.put(_ref(), "")


def test_a_missing_credential_raises_rather_than_returning_none() -> None:
    """A `None` flowing into a connector arrives as an authentication failure,
    which reads as a wrong credential rather than a missing one."""
    vault = Vault(master=MASTER)

    with pytest.raises(CredentialNotFound, match="no credential stored"):
        vault.get(_ref())


def test_deleting_says_whether_there_was_anything_to_delete() -> None:
    vault, _, _, ref = _stocked()

    assert vault.delete(ref) is True
    assert vault.delete(ref) is False
    assert vault.holds(ref) is False


# --- rotation moves the key, not the ciphertext ----------------------------------------


def test_rotation_rewraps_and_leaves_the_ciphertext_alone() -> None:
    """The whole reason the envelope exists: rotation is a metadata operation
    rather than a full read-and-rewrite of every secret."""
    vault, _, _, ref = _stocked()
    before = vault.get(ref)
    new_master = os.urandom(32)

    moved = vault.rotate_master(old_master=MASTER, new_master=new_master)
    after = vault.get(ref)

    assert moved == 1
    assert after.ciphertext == before.ciphertext, "the credential was re-encrypted"
    assert after.wrapped_key != before.wrapped_key
    assert open_sealed(after, master=new_master) == SECRET


def test_the_old_master_stops_opening_a_rotated_record() -> None:
    """The control. A rotation that left the old key working would rotate
    nothing while reporting success."""
    vault, _, _, ref = _stocked()
    new_master = os.urandom(32)
    vault.rotate_master(old_master=MASTER, new_master=new_master)

    with pytest.raises(DecryptionFailed):
        open_sealed(vault.get(ref), master=MASTER)


def test_rotation_moves_every_record_or_none() -> None:
    """A partial rotation leaves some records readable only with the old key and
    some only with the new, and nothing on a record says which - so a failure
    part-way through is discovered as corruption."""
    vault = Vault(master=MASTER)
    refs = [_ref(f"cred-{index}") for index in range(3)]
    for ref in refs:
        vault.put(ref, f"{SECRET}-{ref.name}")
    new_master = os.urandom(32)

    assert vault.rotate_master(old_master=MASTER, new_master=new_master) == 3
    for ref in refs:
        assert open_sealed(vault.get(ref), master=new_master).endswith(ref.name)


# --- redemption checks the lease against the context, not against itself -----------------


def test_a_valid_lease_produces_the_credential() -> None:
    """The control. A redeemer that refused everything would pass every test
    below and be indistinguishable from a broken one."""
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref)

    value = redeem(
        lease,
        vault=vault,
        leases=book,
        connector="postgres",
        investigation_id=RUN,
        master=MASTER,
    )

    assert value == SECRET


def test_another_connector_cannot_redeem_the_lease() -> None:
    """The check that makes "bound to one connector" true rather than
    descriptive. A lease redeemed by a different one is a lease that leaked and
    was used."""
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref, connector="postgres")

    with pytest.raises(RedemptionRefused, match="leaked and was used"):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="kubernetes",
            investigation_id=RUN,
            master=MASTER,
        )


def test_a_lease_cannot_be_carried_into_another_run() -> None:
    """Permission granted for one question is not permission for another."""
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref)

    with pytest.raises(RedemptionRefused, match="not permission for another"):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="postgres",
            investigation_id=uuid4(),
            master=MASTER,
        )


def test_an_expired_lease_produces_nothing() -> None:
    """Checked here and not only at mint, because the interesting gap is between
    the two - a lease sits in an agent's context for the length of a run."""
    vault, book, clock, ref = _stocked()
    lease = _lease(book, ref)

    clock.now = NOW + timedelta(hours=1)

    with pytest.raises(RedemptionRefused, match="silently skipped a check"):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="postgres",
            investigation_id=RUN,
            master=MASTER,
        )


def test_a_lease_for_a_credential_the_vault_lost_refuses() -> None:
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref)
    vault.delete(ref)

    with pytest.raises(RedemptionRefused, match="no credential stored"):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="postgres",
            investigation_id=RUN,
            master=MASTER,
        )


# --- the trail records the event and never the value --------------------------------------


def test_a_redemption_is_recorded_without_the_credential() -> None:
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref)
    audit = AuditLog(secrets=[])

    redeem(
        lease,
        vault=vault,
        leases=book,
        connector="postgres",
        investigation_id=RUN,
        master=MASTER,
        audit=audit,
    )

    entry = audit.entries()[0]
    assert entry.event is AuditEvent.LEASE_USED
    assert entry.lease_id == lease.id
    assert entry.credential_ref == ref
    assert SECRET not in json.dumps(entry.model_dump(mode="json"))


def test_a_refused_redemption_is_recorded_too() -> None:
    """A refusal that raised without a trail would leave "a connector tried to
    redeem a lease it did not hold" in an exception message and nowhere else -
    precisely the event somebody would want to find later."""
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref, connector="postgres")
    audit = AuditLog(secrets=[])

    with pytest.raises(RedemptionRefused):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="kubernetes",
            investigation_id=RUN,
            master=MASTER,
            audit=audit,
        )

    assert [entry.event for entry in audit.entries()] == [AuditEvent.DENIED]


def test_redemption_works_without_an_audit_log() -> None:
    """A connector wired without one must still be refused correctly - the trail
    is a record, not a gate, and confusing the two would make an unaudited path
    a permitted one."""
    vault, book, _, ref = _stocked()
    lease = _lease(book, ref)

    with pytest.raises(RedemptionRefused):
        redeem(
            lease,
            vault=vault,
            leases=book,
            connector="elsewhere",
            investigation_id=RUN,
            master=MASTER,
        )


def test_the_vault_retains_no_plaintext_anywhere_in_its_state() -> None:
    """The claim `put` makes: "nothing in this class holds a decrypted value at
    any point."

    Checking method NAMES was not enough - a plant that simply assigned the
    plaintext to an attribute passed, because a stashed value needs no getter to
    be a leak. It is in a memory dump, in a repr, and in anything that pickles.
    """
    vault, _, _, _ = _stocked()

    state = json.dumps({name: str(value) for name, value in vars(vault).items()}, default=str)

    assert SECRET not in state, "the vault kept the plaintext on the instance"
    assert "hunter2" not in state
    assert SECRET not in repr(vault)
