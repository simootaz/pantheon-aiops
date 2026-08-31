"""Per-type handling, and rotating without breaking a live investigation.

Two questions. How a credential travels is a security property - a kubeconfig
on a command line is in `ps` output for every process on the box. And a
rotation that took the old value away would break every lease already issued
against it, which is the one failure mode a rotation must not have.

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
from core.cerberus.redemption import redeem
from core.cerberus.store.kinds import (
    FORBIDDEN_HANDOFF,
    KINDS,
    CredentialMalformed,
    kind_of,
    validate,
)
from core.cerberus.store.rotation import history, purge, rotate
from core.cerberus.store.vault import Vault
from core.contracts.credentials import (
    AuditEvent,
    CredentialAction,
    CredentialRef,
    CredentialType,
    Grant,
    Handoff,
    PermissionMode,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
RUN = uuid4()
MASTER = os.urandom(32)
OLD = "postgres://user:hunter2@db:5432/prod"
NEW = "postgres://user:correcthorse@db:5432/prod"

#: Assembled rather than written out. A literal PEM block in a test file is a
#: literal PEM block to gitleaks, which cannot tell a fixture from a leak and
#: should not try - so the fixture is built and the scanner is left alone. An
#: allowlist entry here would be a hole in the one guard that catches the real
#: thing, opened to make a test convenient.
_DASHES = "-" * 5
_LABEL = "OPENSSH PRIVATE KEY"
PEM = f"{_DASHES}BEGIN {_LABEL}{_DASHES}\nabc\n{_DASHES}END {_LABEL}{_DASHES}"
TRUNCATED_PEM = f"{_DASHES}BEGIN {_LABEL}{_DASHES}\nabc"
KUBECONFIG = "apiVersion: v1\nclusters: []\ncontexts: []\nusers: []"


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _ref(credential_type: CredentialType = CredentialType.DATABASE) -> CredentialRef:
    return CredentialRef(id=str(uuid4()), name="prod-postgres", type=credential_type)


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


# --- how a credential travels is a security property --------------------------------------


def test_no_credential_type_travels_on_the_command_line() -> None:
    """A kubeconfig passed as an argument is in `ps` output for every process
    on the box and in the shell history of whoever ran it."""
    offenders = [
        credential_type.value
        for credential_type, kind in KINDS.items()
        if kind.handoff is FORBIDDEN_HANDOFF
    ]

    assert not offenders, f"{offenders} would put a secret on the command line"


def test_every_credential_type_declares_how_it_travels() -> None:
    """A type with no entry is one somebody added to the enum without deciding
    how it reaches a connector."""
    undeclared = [
        credential_type.value for credential_type in CredentialType if credential_type not in KINDS
    ]

    assert not undeclared, f"{undeclared} have no declared handling"


def test_a_multiline_credential_travels_as_a_file_and_not_an_environment_variable() -> None:
    """A PEM key in an environment variable survives, and it is in
    `/proc/<pid>/environ` for the life of the process and in every crash dump
    and child process it spawns."""
    assert kind_of(CredentialType.SSH).handoff is Handoff.FILE
    assert kind_of(CredentialType.KUBECONFIG).handoff is Handoff.FILE
    assert kind_of(CredentialType.TLS).handoff is Handoff.FILE


def test_a_type_added_to_the_enum_without_handling_raises() -> None:
    """The real shape of the omission: somebody adds a member to
    `CredentialType` and does not reach `KINDS`.

    Defaulting to an environment variable would hide it behind a channel
    nobody chose - a kubeconfig-sized secret in `/proc/<pid>/environ` because
    a commit was left half finished.
    """
    forgotten = KINDS.pop(CredentialType.KUBECONFIG)
    try:
        with pytest.raises(CredentialMalformed, match="no handling declared"):
            kind_of(CredentialType.KUBECONFIG)
    finally:
        KINDS[CredentialType.KUBECONFIG] = forgotten

    assert kind_of(CredentialType.KUBECONFIG) is forgotten, "the fixture leaked"


# --- validation catches shape, never correctness --------------------------------------------


def test_a_newline_in_an_http_credential_is_refused() -> None:
    """Header injection. It splits the request carrying it, it is reachable by
    anyone who can set a credential, and it is one line to check."""
    with pytest.raises(CredentialMalformed, match="header injection"):
        validate(CredentialType.HTTP_AUTH, "Bearer abc\r\nX-Admin: true")


def test_a_newline_is_fine_in_a_credential_that_travels_as_a_file() -> None:
    """The control. Refusing every newline would refuse every PEM key, and the
    check would be about newlines rather than about headers.

    Asserted through the vault rather than by "it did not raise", so the claim
    is that a real multi-line key is storable and not merely that one function
    stayed quiet.
    """
    vault = Vault(master=MASTER)
    ref = _ref(CredentialType.SSH)

    vault.put(ref, PEM)

    assert vault.holds(ref)


def test_a_truncated_pem_key_is_refused() -> None:
    """A BEGIN with no END is how a key copied from a wrapped terminal
    arrives, and it fails at use with a parse error from inside a crypto
    library."""
    with pytest.raises(CredentialMalformed, match="complete PEM block"):
        validate(CredentialType.SSH, TRUNCATED_PEM)


def test_a_kubeconfig_without_a_cluster_is_refused() -> None:
    with pytest.raises(CredentialMalformed, match="clusters"):
        validate(CredentialType.KUBECONFIG, "apiVersion: v1\ncontexts: []\nusers: []")


def test_a_keyword_connection_string_is_as_valid_as_a_uri() -> None:
    """Rejecting `host=db user=x` would refuse a correct credential to enforce
    a preference."""
    validate(CredentialType.DATABASE, "host=db user=x password=y")
    validate(CredentialType.DATABASE, OLD)

    with pytest.raises(CredentialMalformed, match="neither a URI"):
        validate(CredentialType.DATABASE, "just-a-password")


def test_an_opaque_type_is_checked_for_emptiness_and_nothing_else() -> None:
    """Inventing a pattern for a cloud key would reject the next provider's
    format for no reason."""
    validate(CredentialType.CLOUD_KEY, "AKIA-whatever-shape-this-vendor-uses")

    with pytest.raises(CredentialMalformed, match="is empty"):
        validate(CredentialType.CLOUD_KEY, "   ")


def test_the_vault_refuses_a_malformed_credential_at_put_time() -> None:
    """Not at redemption. A malformed credential found at 03:00 during an
    incident presents as the connector being broken, and whoever is paged
    spends the first twenty minutes on the wrong system."""
    vault = Vault(master=MASTER)

    with pytest.raises(CredentialMalformed):
        vault.put(_ref(CredentialType.SSH), "not a key")

    assert len(vault) == 0


# --- rotation keeps a live lease working ------------------------------------------------------


def _rotating() -> tuple[Vault, LeaseBook, _Ticker, CredentialRef]:
    ref = _ref()
    vault = Vault(master=MASTER)
    vault.put(ref, OLD)
    clock = _Ticker()
    return vault, LeaseBook(clock=clock), clock, ref


def _lease(book: LeaseBook, ref: CredentialRef):  # type: ignore[no-untyped-def]
    return book.mint(
        _grant(ref),
        investigation_id=RUN,
        connector="postgres",
        action=CredentialAction.READ,
        request_id=uuid4(),
    )


def _redeem(lease, vault: Vault, book: LeaseBook) -> str:  # type: ignore[no-untyped-def]
    return redeem(
        lease,
        vault=vault,
        leases=book,
        connector="postgres",
        investigation_id=RUN,
        master=MASTER,
    )


def test_a_lease_minted_in_the_same_tick_as_the_rotation_keeps_the_old_value() -> None:
    """A lease issued at the exact moment of the rotation is a lease in
    flight, which is the entire population retention exists for. Under a
    coarse clock, mint-then-rotate inside one tick is the common case rather
    than an edge one, and a strict boundary hands it the new value."""
    vault, book, _, ref = _rotating()
    lease = _lease(book, ref)

    rotate(ref, NEW, vault=vault, leases=book, now=lease.issued_at)

    assert _redeem(lease, vault, book) == OLD


def test_a_lease_issued_before_the_rotation_still_gets_the_old_value() -> None:
    """The whole reason retention exists. Without it a rotation breaks every
    investigation already holding a lease, and it presents as an
    authentication failure against a system that was working a second ago.
    """
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)
    clock.now = NOW + timedelta(seconds=30)

    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    assert _redeem(lease, vault, book) == OLD


def test_a_lease_issued_after_the_rotation_gets_the_new_value() -> None:
    """The control. A vault that always answered with the retired version
    would pass the test above and have rotated nothing."""
    vault, book, clock, ref = _rotating()

    clock.now = NOW + timedelta(seconds=1)
    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)
    clock.now = NOW + timedelta(seconds=2)
    lease = _lease(book, ref)

    assert _redeem(lease, vault, book) == NEW


def test_the_retention_window_is_the_last_live_lease_and_not_a_setting() -> None:
    """At rotation the latest expiry among live leases is already known. That
    moment is exactly when the old version stops being reachable, so there is
    nothing to configure and nothing to tune."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)

    rotation = rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    assert rotation.retained_until == lease.expires_at
    assert rotation.leases_carried == 1
    assert rotation.retained


def test_with_no_live_lease_the_old_value_is_retired_immediately() -> None:
    """Keeping it "just in case" would keep a superseded secret redeemable for
    a window nobody chose."""
    vault, book, clock, ref = _rotating()

    rotation = rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    assert rotation.retained_until == clock.now
    assert not rotation.retained


def test_the_old_value_stops_being_reachable_once_the_window_closes() -> None:
    """Answered on read. A lease past its own expiry cannot redeem at all, so
    this is asserted on the vault, where the window actually lives."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)
    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    after = lease.expires_at + timedelta(seconds=1)
    sealed = vault.version_for(ref, issued_at=lease.issued_at, now=after)

    assert sealed == vault.get(ref), "the retired value outlived its window"


def test_a_rotation_to_a_malformed_value_changes_nothing() -> None:
    """The one failure mode a rotation must not have: the credential rotated
    to something unusable and the old one already superseded."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)

    with pytest.raises(CredentialMalformed):
        rotate(ref, "not-a-connection-string", vault=vault, leases=book, now=clock.now)

    assert _redeem(lease, vault, book) == OLD


def test_purging_changes_no_answer() -> None:
    """It reclaims memory. A system that never purges resolves exactly as one
    that purges every second, which is what makes it safe on a timer."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)
    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    assert purge(vault, now=clock.now) == 0, "purged a version a live lease still needs"
    assert _redeem(lease, vault, book) == OLD

    assert purge(vault, now=lease.expires_at + timedelta(seconds=1)) == 1
    assert purge(vault, now=lease.expires_at + timedelta(seconds=1)) == 0


def test_a_master_rotation_carries_the_retired_versions_too() -> None:
    """Leaving them wrapped under the old master would silently destroy every
    value a live lease still resolves to, and the failure would arrive at
    redemption as a decryption error - which reads as corruption."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)
    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    vault.rotate_master(old_master=MASTER, new_master=os.urandom(32))

    sealed = vault.version_for(ref, issued_at=lease.issued_at, now=clock.now)
    assert sealed is not None


def test_deleting_a_credential_takes_its_retired_version_with_it() -> None:
    """A superseded value outliving the credential it belongs to is reachable
    through a lease that predates the rotation - a deletion that deleted
    nothing."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)
    rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    vault.delete(ref)

    with pytest.raises(KeyError):
        vault.version_for(ref, issued_at=lease.issued_at, now=clock.now)


def test_a_rotation_is_recorded_without_either_value() -> None:
    vault, book, clock, ref = _rotating()
    audit = AuditLog(secrets=[])

    rotate(ref, NEW, vault=vault, leases=book, by="alex", audit=audit, now=clock.now)

    entry = audit.entries()[-1]
    assert entry.event is AuditEvent.ROTATED
    assert OLD not in entry.detail and NEW not in entry.detail
    assert "correcthorse" not in entry.detail and "hunter2" not in entry.detail


def test_a_rotation_says_what_it_carried_and_until_when() -> None:
    """The line somebody reads after pulling a rotation. "rotated" alone
    cannot answer the question that follows it - whether anything is still
    holding the previous value, and for how long."""
    vault, book, clock, ref = _rotating()
    lease = _lease(book, ref)

    carried = rotate(ref, NEW, vault=vault, leases=book, now=clock.now)

    rendered = str(carried)
    assert "1 live leases" in rendered
    assert lease.expires_at.isoformat() in rendered
    assert OLD not in rendered and NEW not in rendered


def test_a_rotation_with_nothing_live_says_so_rather_than_reporting_zero() -> None:
    """The control, and the more common case. "0 live leases keep the previous
    value until <now>" is a sentence that invites a second reading."""
    vault, book, clock, ref = _rotating()

    rendered = str(rotate(ref, NEW, vault=vault, leases=book, now=clock.now))

    assert "no lease was live" in rendered


# --- the wire form, and a history nobody stores twice -----------------------------------


def test_a_descriptor_says_how_a_credential_travels_and_never_what_it_is() -> None:
    """The invariant the whole credential contract surface is checked against.

    A field for the value here would make this the first contract able to carry
    a secret into a JSON Schema, a Go struct and a TypeScript type in one
    commit. `channel` is a filename.
    """
    descriptor = kind_of(CredentialType.KUBECONFIG).descriptor()

    assert descriptor.handoff is Handoff.FILE
    assert descriptor.channel == "kubeconfig"

    rendered = json.dumps(descriptor.model_dump(mode="json"))
    assert OLD not in rendered and "hunter2" not in rendered


def test_the_descriptor_agrees_with_the_kind_it_came_from() -> None:
    """Built rather than declared twice. Two definitions of how a kubeconfig
    travels is one that can disagree with the other, and the one a dashboard
    reads would be the one nobody tests."""
    for credential_type, kind in KINDS.items():
        descriptor = kind.descriptor()
        assert (descriptor.type, descriptor.handoff, descriptor.channel) == (
            credential_type,
            kind.handoff,
            kind.channel,
        )


def test_the_rotation_history_is_read_out_of_the_trail() -> None:
    """Derived, not stored beside it. A second store is a second thing to keep
    in sync, and the one that drifts is the one somebody consults to answer
    "when was this last rotated"."""
    vault, book, clock, ref = _rotating()
    audit = AuditLog(secrets=[])

    # Other events first, so "only rotations" is a claim the fixture can
    # express. Without them the filter has nothing to exclude, and a plant
    # accepting every event passed - a trail in real life is almost entirely
    # lease traffic.
    lease = _lease(book, ref)
    _redeem(lease, vault, book)
    audit.append(
        AuditEvent.LEASE_USED,
        actor="postgres",
        credential_ref=ref,
        action=CredentialAction.READ,
        detail="redeemed",
    )
    audit.append(AuditEvent.DENIED, actor="argus", credential_ref=ref, detail="refused")

    rotate(ref, NEW, vault=vault, leases=book, by="alex", audit=audit, now=clock.now)

    (record,) = history(audit)
    assert record.credential_ref.id == ref.id
    assert record.rotated_by == "alex"
    assert record.rotated_at == audit.entries()[-1].at


def test_the_history_of_one_credential_excludes_another() -> None:
    """A rotation attributed to the wrong credential is worse than none."""
    vault, book, clock, ref = _rotating()
    other = _ref()
    vault.put(other, OLD)
    audit = AuditLog(secrets=[])

    rotate(ref, NEW, vault=vault, leases=book, audit=audit, now=clock.now)
    rotate(other, NEW, vault=vault, leases=book, audit=audit, now=clock.now)

    assert len(history(audit)) == 2
    assert [record.credential_ref.id for record in history(audit, ref=other)] == [other.id]


def test_the_history_carries_no_value() -> None:
    vault, book, clock, ref = _rotating()
    audit = AuditLog(secrets=[])
    rotate(ref, NEW, vault=vault, leases=book, audit=audit, now=clock.now)

    rendered = json.dumps([record.model_dump(mode="json") for record in history(audit)])

    assert OLD not in rendered and NEW not in rendered
    assert "hunter2" not in rendered and "correcthorse" not in rendered


def test_a_trail_with_no_rotations_has_an_empty_history() -> None:
    """Not an error and not a None. A credential nobody has rotated has a
    history of length zero, which is the honest answer to "when was this last
    rotated"."""
    assert history(AuditLog(secrets=[])) == []
