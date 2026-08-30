"""Leases: bound to one connector, one run, and one grant that is still alive.

Binding all three is what makes a leaked lease worthless. Each test below is one
of the ways a lease could be worth something to someone who stole it, or worth
more than the grant behind it ever gave.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from core.cerberus.lease import (
    MAX_RENEWALS,
    LeaseBook,
    LeaseExpired,
    LeaseNotRenewable,
)
from core.contracts.credentials import (
    CredentialAction,
    CredentialRef,
    CredentialType,
    Grant,
    PermissionMode,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
RUN = uuid4()


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _ref() -> CredentialRef:
    return CredentialRef(id=str(uuid4()), name="prod-postgres", type=CredentialType.DATABASE)


def _grant(
    *,
    mode: PermissionMode = PermissionMode.ALLOW_UNTIL,
    action: CredentialAction = CredentialAction.READ,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    investigation_id: object = None,
) -> Grant:
    return Grant(
        id=uuid4(),
        agent="argus",
        credential_ref=_ref(),
        action=action,
        mode=mode,
        investigation_id=investigation_id,  # type: ignore[arg-type]
        expires_at=expires_at if expires_at is not None else NOW + timedelta(hours=1),
        granted_by="alex",
        granted_at=NOW,
        revoked_at=revoked_at,
    )


def _book(clock: _Ticker | None = None, **kwargs: object) -> tuple[LeaseBook, _Ticker]:
    ticker = clock or _Ticker()
    return LeaseBook(clock=ticker, **kwargs), ticker  # type: ignore[arg-type]


def _mint(book: LeaseBook, grant: Grant, **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "investigation_id": RUN,
        "connector": "postgres",
        "action": grant.action,
        "request_id": uuid4(),
    }
    kwargs.update(overrides)
    return book.mint(grant, **kwargs)  # type: ignore[arg-type]


# --- a lease is bound, and the binding is what makes a leak worthless ----------------


def test_a_lease_names_the_one_connector_that_may_redeem_it() -> None:
    book, _ = _book()

    lease = _mint(book, _grant())

    assert lease.connector == "postgres"  # type: ignore[attr-defined]
    assert lease.investigation_id == RUN  # type: ignore[attr-defined]


def test_a_lease_carries_a_reference_and_never_a_value() -> None:
    """The property that makes it safe to log and safe to put on an
    Investigation an agent can read."""
    book, _ = _book()
    grant = _grant()

    lease = _mint(book, grant)

    assert lease.credential_ref == grant.credential_ref  # type: ignore[attr-defined]
    rendered = lease.model_dump_json()  # type: ignore[attr-defined]
    assert "password" not in rendered and "secret" not in rendered


def test_a_lease_cannot_widen_what_was_granted() -> None:
    """A grant to READ does not become a lease to WRITE by asking."""
    book, _ = _book()

    with pytest.raises(LeaseExpired, match="cannot widen"):
        _mint(book, _grant(action=CredentialAction.READ), action=CredentialAction.WRITE)


def test_a_grant_scoped_to_one_run_does_not_carry_into_another() -> None:
    """That is the whole of what ALLOW_FOR_INVESTIGATION means, and it would be
    a quiet no-op if minting ignored it."""
    book, _ = _book()
    grant = _grant(mode=PermissionMode.ALLOW_FOR_INVESTIGATION, investigation_id=RUN)

    _mint(book, grant)  # the run it was granted for

    with pytest.raises(LeaseExpired, match="does not carry into another"):
        _mint(book, grant, investigation_id=uuid4())


# --- the grant behind it must be alive --------------------------------------------------


def test_a_revoked_grant_mints_nothing() -> None:
    """Permission nobody currently holds - and the lease would look identical to
    a valid one for its whole life."""
    book, _ = _book()

    with pytest.raises(LeaseExpired, match="was revoked"):
        _mint(book, _grant(revoked_at=NOW - timedelta(minutes=1)))


def test_an_expired_grant_mints_nothing() -> None:
    book, _ = _book()

    with pytest.raises(LeaseExpired, match="expired at"):
        _mint(book, _grant(expires_at=NOW - timedelta(minutes=1)))


def test_a_deny_grant_mints_nothing() -> None:
    """Minting against one would turn a recorded refusal into permission."""
    book, _ = _book()

    with pytest.raises(LeaseExpired, match="is a DENY"):
        _mint(book, _grant(mode=PermissionMode.DENY))


# --- a lease never outlives its grant -----------------------------------------------------


def test_a_lease_expires_no_later_than_its_grant() -> None:
    """Permission nobody gave, arrived at by arithmetic."""
    book, _ = _book(ttl=timedelta(hours=6))
    grant = _grant(expires_at=NOW + timedelta(minutes=10))

    lease = _mint(book, grant)

    assert lease.expires_at == grant.expires_at  # type: ignore[attr-defined]


def test_an_unbounded_grant_leaves_the_ttl_as_the_only_limit() -> None:
    """Only ALLOW_UNTIL sets an expiry, so the short TTL is what bounds a lease
    under a grant that names no end - which is why the TTL is minutes."""
    book, _ = _book(ttl=timedelta(minutes=5))
    grant = _grant(mode=PermissionMode.ALLOW_FOR_INVESTIGATION, investigation_id=RUN)
    grant = grant.model_copy(update={"expires_at": None})

    lease = _mint(book, grant)

    assert lease.expires_at == NOW + timedelta(minutes=5)  # type: ignore[attr-defined]


def test_renewal_does_not_reach_past_the_grant() -> None:
    """The renewal is exactly where a lease would outlive its grant without
    anyone deciding to."""
    book, clock = _book(ttl=timedelta(minutes=30))
    grant = _grant(expires_at=NOW + timedelta(minutes=40))
    lease = _mint(book, grant)

    clock.now = NOW + timedelta(minutes=20)
    renewed = book.renew(lease)  # type: ignore[arg-type]

    assert renewed.expires_at == grant.expires_at


# --- renewal, and its four different refusals ---------------------------------------------


def test_a_live_lease_renews() -> None:
    """The control. A book that refused every renewal would pass the rest."""
    book, clock = _book(ttl=timedelta(minutes=5))
    lease = _mint(book, _grant())

    clock.now = NOW + timedelta(minutes=2)
    renewed = book.renew(lease)  # type: ignore[arg-type]

    assert renewed.renewed_count == 1
    assert renewed.expires_at > lease.expires_at  # type: ignore[attr-defined]


def test_a_non_renewable_lease_refuses_with_its_own_reason() -> None:
    """Not `LeaseExpired`. An agent told "expired" would surface a Finding about
    a grant that is perfectly alive."""
    book, _ = _book()
    lease = _mint(book, _grant(), renewable=False)

    with pytest.raises(LeaseNotRenewable, match="non-renewable"):
        book.renew(lease)  # type: ignore[arg-type]


def test_renewal_is_bounded() -> None:
    """An agent looping on a renewal it never uses is indistinguishable from one
    making progress, and both keep a credential reachable indefinitely."""
    book, _ = _book()
    lease = _mint(book, _grant())

    for _ in range(MAX_RENEWALS):
        lease = book.renew(lease)  # type: ignore[arg-type]

    with pytest.raises(LeaseNotRenewable, match="the limit is"):
        book.renew(lease)  # type: ignore[arg-type]


def test_renewing_after_the_grant_died_is_a_lease_expiry() -> None:
    """The one an agent must surface as a Finding rather than swallow, so the
    run completes visibly partial instead of quietly short."""
    book, clock = _book()
    grant = _grant(expires_at=NOW + timedelta(minutes=10))
    lease = _mint(book, grant)

    clock.now = NOW + timedelta(minutes=11)

    with pytest.raises(LeaseExpired, match="visibly partial"):
        book.renew(lease)  # type: ignore[arg-type]


def test_a_lease_this_book_never_minted_cannot_be_renewed() -> None:
    """Otherwise a forged lease renews itself into existence."""
    book, _ = _book()
    other, _ = _book()
    lease = _mint(other, _grant())

    with pytest.raises(LeaseExpired, match="not minted here"):
        book.renew(lease)  # type: ignore[arg-type]


# --- expiry and revocation ------------------------------------------------------------------


def test_expiry_is_answered_on_read() -> None:
    """A sweep would make "expired" depend on whether the sweep ran."""
    book, clock = _book(ttl=timedelta(minutes=5))
    lease = _mint(book, _grant())

    assert book.live(lease)  # type: ignore[arg-type]
    clock.now = NOW + timedelta(minutes=6)
    assert not book.live(lease)  # type: ignore[arg-type]


def test_revoking_expires_a_lease_rather_than_deleting_it() -> None:
    """A lease that vanished would make a later redemption fail with "unknown
    lease", which reads as a bug in whoever held it rather than as a revocation
    somebody performed."""
    book, _ = _book()
    lease = _mint(book, _grant())

    assert book.revoke(lease.id) is True  # type: ignore[attr-defined]

    with pytest.raises((LeaseNotRenewable, LeaseExpired)):
        book.renew(lease)  # type: ignore[arg-type]


def test_revoking_something_that_was_never_minted_says_so() -> None:
    book, _ = _book()

    assert book.revoke(uuid4()) is False


def test_nothing_here_can_produce_a_credential() -> None:
    """A lease is permission, not a secret. `core/cerberus/redemption.py` is the
    only module that yields plaintext, and this one must never grow a path to
    one - asserted on the surface, because that growth would be one method."""
    from core.cerberus import lease as module

    surface = {name for name in vars(module) if not name.startswith("_")}
    forbidden = {"decrypt", "reveal", "plaintext", "secret", "redeem", "value"}

    assert not surface & forbidden, f"the lease module exposes {surface & forbidden}"
