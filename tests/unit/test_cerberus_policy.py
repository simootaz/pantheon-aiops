"""Policy: who may reach which credential, in what way, and for how long.

Every test here is a way permission could be wider than somebody meant it to
be - a staging grant answering a production request, a read grant satisfying a
write, a lapsed grant reading as a refusal, a revocation that takes effect in
five minutes.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.cerberus.policy import evaluate
from core.cerberus.policy.defaults import (
    UnsafeGrant,
    ask_by_default,
    is_production,
    refuse_unsafe_grant,
)
from core.cerberus.policy.grants import GrantBook
from core.cerberus.policy.modes import Answer, answer
from core.cerberus.policy.scope import covers, describe, specificity
from core.contracts.credentials import (
    AccessRequest,
    CredentialAction,
    CredentialRef,
    CredentialScope,
    CredentialType,
    Grant,
    PermissionMode,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
RUN = uuid4()
CRED_ID = "cred-1"


class _Ticker:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _scope(**fields: str) -> CredentialScope:
    return CredentialScope(**fields)


def _ref(name: str = "prod-postgres", **fields: str) -> CredentialRef:
    return CredentialRef(
        id=CRED_ID, name=name, type=CredentialType.DATABASE, scope=_scope(**fields)
    )


def _grant(
    *,
    agent: str = "argus",
    action: CredentialAction = CredentialAction.READ,
    mode: PermissionMode = PermissionMode.ALLOW_UNTIL,
    ref: CredentialRef | None = None,
    investigation_id: UUID | None = None,
    expires_at: datetime | None = NOW + timedelta(hours=1),
    revoked_at: datetime | None = None,
    granted_at: datetime = NOW,
    override: bool = True,
) -> Grant:
    return Grant(
        id=uuid4(),
        agent=agent,
        credential_ref=ref if ref is not None else _ref(environment="staging"),
        action=action,
        mode=mode,
        investigation_id=investigation_id,
        expires_at=expires_at,
        granted_by="alex",
        granted_at=granted_at,
        override_ask_default=override,
        revoked_at=revoked_at,
    )


def _request(
    *,
    agent: str = "argus",
    action: CredentialAction = CredentialAction.READ,
    ref: CredentialRef | None = None,
    investigation_id: UUID = RUN,
    ttl_seconds: int = 3600,
) -> AccessRequest:
    return AccessRequest(
        id=uuid4(),
        investigation_id=investigation_id,
        agent=agent,
        credential_ref=ref if ref is not None else _ref(environment="staging"),
        action=action,
        reason="connection saturation may explain the p99 latency",
        requested_ttl_seconds=ttl_seconds,
        requested_at=NOW,
    )


# --- scope: unset on a grant is "any", unset on a request is "unknown" -----------------


def test_a_wildcard_grant_covers_a_named_request() -> None:
    assert covers(_scope(), _scope(environment="prod", server="db-01"))


def test_a_named_grant_does_not_cover_a_different_value() -> None:
    """The one this module exists for: a staging grant must never satisfy a
    production request."""
    assert not covers(_scope(environment="staging"), _scope(environment="prod"))


def test_a_named_grant_does_not_cover_a_request_that_named_nothing() -> None:
    """The asymmetry, and the failure it prevents.

    A request naming no environment is a question nobody answered, and it might
    be production. Treating unknown as a wildcard would let a staging grant
    answer it - and the request that slipped through looks identical to one
    that legitimately matched.
    """
    assert not covers(_scope(environment="staging"), _scope())


def test_a_grant_matches_only_when_every_named_field_matches() -> None:
    """Field by field, not any-of. One matching field out of two is a grant
    written about a different target that happens to share a name."""
    grant = _scope(environment="prod", service="checkout")

    assert covers(grant, _scope(environment="prod", service="checkout", server="db-01"))
    assert not covers(grant, _scope(environment="prod", service="payments"))


def test_specificity_counts_named_fields() -> None:
    assert specificity(_scope()) == 0
    assert specificity(_scope(environment="prod")) == 1
    assert specificity(_scope(environment="prod", server="db-01")) == 2


def test_a_scope_describes_itself_for_a_refusal_message() -> None:
    """At 03:00 the question is which scope, so the refusal has to say."""
    assert describe(_scope()) == "unscoped"
    assert "environment=prod" in describe(_scope(environment="prod"))


# --- defaults: the posture, and what it takes to widen it -------------------------------


def test_an_unnamed_environment_is_production() -> None:
    """Reading unset as "not production" would make the widest credential in
    the system the one that skips the production check."""
    assert is_production(_ref()) is True


def test_an_unrecognised_environment_is_production() -> None:
    """`prod-eu` is on neither list. Guessing wrong in the safe direction costs
    an approval prompt; guessing wrong in the other costs an incident."""
    assert is_production(_ref(environment="prod-eu")) is True
    assert is_production(_ref(environment="staging")) is False


def test_every_write_asks_whatever_the_environment() -> None:
    reason = ask_by_default(_ref(environment="staging"), CredentialAction.WRITE)

    assert reason is not None
    assert "changes a system" in reason


def test_a_production_read_asks_and_a_staging_read_does_not() -> None:
    """Both directions. A posture that asked about everything would pass the
    first half of this and be useless."""
    assert ask_by_default(_ref(environment="prod"), CredentialAction.READ) is not None
    assert ask_by_default(_ref(environment="staging"), CredentialAction.READ) is None


def test_a_standing_grant_on_production_is_refused_without_the_override() -> None:
    with pytest.raises(UnsafeGrant, match="would outlive every run"):
        refuse_unsafe_grant(
            _grant(ref=_ref(environment="prod"), mode=PermissionMode.ALLOW_UNTIL, override=False)
        )


def test_a_standing_write_grant_is_refused_without_the_override() -> None:
    with pytest.raises(UnsafeGrant, match="changes a system"):
        refuse_unsafe_grant(
            _grant(
                ref=_ref(environment="staging"),
                action=CredentialAction.WRITE,
                mode=PermissionMode.ALLOW_UNTIL,
                override=False,
            )
        )


def test_the_override_is_what_makes_it_deliberate() -> None:
    """The control. A check that refused every ALLOW_UNTIL would pass both
    tests above and make the flag meaningless.

    Asserted through the book rather than by "it did not raise", so the claim
    is that the safe path produces a grant somebody can actually use.
    """
    book = GrantBook()

    grant = book.register(
        _grant(ref=_ref(environment="prod"), mode=PermissionMode.ALLOW_UNTIL, override=True)
    )

    assert book.get(grant.id) is not None


def test_an_investigation_scoped_grant_needs_no_override() -> None:
    """It dies with the run that asked for it, so its blast radius is bounded
    by the reason it was given - which is the whole of what the mode is for."""
    book = GrantBook()

    grant = book.register(
        _grant(
            ref=_ref(environment="prod"),
            mode=PermissionMode.ALLOW_FOR_INVESTIGATION,
            investigation_id=RUN,
            override=False,
        )
    )

    assert book.get(grant.id) is not None


# --- modes: which no ---------------------------------------------------------------------


def test_a_deny_answers_deny_even_after_it_was_revoked() -> None:
    """Reading a revoked DENY as "no permission" would let the next broad ALLOW
    answer instead, which turns deleting a deny into a way of granting access."""
    verdict = answer(
        _grant(mode=PermissionMode.DENY, revoked_at=NOW - timedelta(days=1)),
        investigation_id=RUN,
        now=NOW,
    )

    assert verdict.answer is Answer.DENY


def test_a_revoked_grant_asks_rather_than_denies() -> None:
    """A grant that lapsed on Friday and one somebody set to DENY lead to
    opposite conversations: "renew it" and "no, and here is why"."""
    verdict = answer(_grant(revoked_at=NOW - timedelta(minutes=1)), investigation_id=RUN, now=NOW)

    assert verdict.answer is Answer.ASK
    assert "revoked" in verdict.why
    assert not verdict.allowed


def test_an_expired_grant_asks() -> None:
    verdict = answer(_grant(expires_at=NOW - timedelta(minutes=1)), investigation_id=RUN, now=NOW)

    assert verdict.answer is Answer.ASK
    assert "lapsed grant" in verdict.why


def test_ask_each_time_records_eligibility_and_not_permission() -> None:
    verdict = answer(_grant(mode=PermissionMode.ASK_EACH_TIME), investigation_id=RUN, now=NOW)

    assert verdict.answer is Answer.ASK


def test_an_investigation_grant_allows_its_own_run_and_no_other() -> None:
    """Both directions in one test, because the mode means nothing unless the
    second half fails."""
    grant = _grant(mode=PermissionMode.ALLOW_FOR_INVESTIGATION, investigation_id=RUN)

    assert answer(grant, investigation_id=RUN, now=NOW).answer is Answer.ALLOW
    assert answer(grant, investigation_id=uuid4(), now=NOW).answer is Answer.ASK


def test_a_live_standing_grant_allows() -> None:
    verdict = answer(_grant(), investigation_id=RUN, now=NOW)

    assert verdict.allowed
    assert verdict.grant_id is not None


# --- grants: matching is exact, selection is ordered --------------------------------------


def test_a_read_grant_never_satisfies_a_write_request() -> None:
    """The single most consequential widening this module could permit, and it
    would happen through an `in` where an `is` belonged."""
    book = GrantBook()
    book.register(_grant(action=CredentialAction.READ))

    verdict = book.evaluate(_request(action=CredentialAction.WRITE), now=NOW)

    assert verdict.answer is Answer.ASK
    assert "changes a system" in verdict.why


def test_a_grant_for_another_agent_does_not_answer() -> None:
    book = GrantBook()
    book.register(_grant(agent="hermes"))

    assert book.evaluate(_request(agent="argus"), now=NOW).answer is Answer.ASK


def test_a_staging_grant_does_not_answer_a_production_request() -> None:
    book = GrantBook()
    book.register(_grant(ref=_ref(environment="staging")))

    verdict = book.evaluate(_request(ref=_ref(environment="prod")), now=NOW)

    assert verdict.answer is Answer.ASK
    assert verdict.grant_id is None


def test_a_broad_deny_beats_a_narrow_allow() -> None:
    """Otherwise an operator adding a deny must also find and delete every
    allow that could outrank it - revocation becomes a search problem, which is
    the thing nobody can do at 03:00."""
    book = GrantBook()
    book.register(_grant(ref=_ref(), mode=PermissionMode.DENY, expires_at=None))
    narrow = book.register(_grant(ref=_ref(environment="prod", server="db-01")))

    verdict = book.evaluate(_request(ref=_ref(environment="prod", server="db-01")), now=NOW)

    assert verdict.answer is Answer.DENY
    assert verdict.grant_id != narrow.id


def test_the_narrowest_grant_answers() -> None:
    """A grant naming a server was written about that server; a wildcard was
    written about everything, including things nobody had in mind yet."""
    book = GrantBook()
    book.register(_grant(ref=_ref(), mode=PermissionMode.ASK_EACH_TIME, expires_at=None))
    narrow = book.register(_grant(ref=_ref(environment="prod", server="db-01")))

    verdict = book.evaluate(_request(ref=_ref(environment="prod", server="db-01")), now=NOW)

    assert verdict.answer is Answer.ALLOW
    assert verdict.grant_id == narrow.id


def test_a_narrow_ask_outranks_a_broad_allow() -> None:
    """The other direction of the same rule, and the one that matters: somebody
    wrote ASK_EACH_TIME about this specific target on purpose."""
    book = GrantBook()
    book.register(_grant(ref=_ref(), expires_at=None))
    narrow = book.register(
        _grant(ref=_ref(environment="prod", server="db-01"), mode=PermissionMode.ASK_EACH_TIME)
    )

    verdict = book.evaluate(_request(ref=_ref(environment="prod", server="db-01")), now=NOW)

    assert verdict.answer is Answer.ASK
    assert verdict.grant_id == narrow.id


def test_equal_scopes_are_broken_by_the_later_decision() -> None:
    """Two grants of equal scope are two decisions, and the later one was made
    knowing about the earlier."""
    book = GrantBook()
    book.register(
        _grant(
            ref=_ref(environment="prod"),
            mode=PermissionMode.ASK_EACH_TIME,
            granted_at=NOW - timedelta(days=2),
        )
    )
    later = book.register(_grant(ref=_ref(environment="prod"), granted_at=NOW - timedelta(hours=1)))

    verdict = book.evaluate(_request(ref=_ref(environment="prod")), now=NOW)

    assert verdict.grant_id == later.id


def test_no_grant_at_all_asks_with_the_default_posture() -> None:
    verdict = evaluate(_request(ref=_ref(environment="prod")), grants=GrantBook(), now=NOW)

    assert verdict.answer is Answer.ASK
    assert "Production reads ask by default" in verdict.why


def test_no_grant_and_no_default_still_asks_and_says_nobody_considered_it() -> None:
    """A staging read triggers no default, so the reason has to come from
    somewhere - and "nobody has considered this" is a different sentence from
    "the posture forbids it"."""
    verdict = evaluate(_request(ref=_ref(environment="staging")), grants=GrantBook(), now=NOW)

    assert verdict.answer is Answer.ASK
    assert "Nobody has considered" in verdict.why


def test_registering_an_unsafe_grant_is_refused_at_the_book() -> None:
    """Checked when the grant is registered, not when it is used. An unsafe
    grant looking valid until the moment it mattered is a refusal at 03:00 for
    a decision somebody made calmly weeks earlier."""
    book = GrantBook()

    with pytest.raises(UnsafeGrant):
        book.register(
            _grant(ref=_ref(environment="prod"), mode=PermissionMode.ALLOW_UNTIL, override=False)
        )

    assert book.all() == []


def test_revoked_grants_stay_in_the_book() -> None:
    """Revoked is a state, not a deletion - the trail keeps the shape of what
    was permitted."""
    book = GrantBook()
    grant = book.register(_grant())

    assert book.mark_revoked(grant.id, at=NOW) is True
    assert book.mark_revoked(grant.id, at=NOW) is False, "revoking twice counted twice"
    assert len(book.all()) == 1
    assert book.held_by("argus")[0].revoked_at == NOW
