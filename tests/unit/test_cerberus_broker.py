"""The broker, and taking permission back.

The broker is the only Cerberus module an agent may touch. Every test here is
either a way it could hand back more than policy allowed, or a way a revocation
could turn out to be advisory.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from core.cerberus.audit.log import AuditLog
from core.cerberus.broker import AccessRefused, ApprovalRequired, Cerberus
from core.cerberus.lease import LeaseBook
from core.cerberus.policy.grants import GrantBook
from core.cerberus.policy.revocation import break_glass, revoke_agent, revoke_grant
from core.contracts.credentials import (
    AccessRequest,
    AuditEvent,
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


def _ref(**fields: str) -> CredentialRef:
    return CredentialRef(
        id=CRED_ID,
        name="staging-postgres",
        type=CredentialType.DATABASE,
        scope=CredentialScope(**fields),
    )


def _grant(
    *,
    agent: str = "argus",
    action: CredentialAction = CredentialAction.READ,
    mode: PermissionMode = PermissionMode.ALLOW_UNTIL,
    ref: CredentialRef | None = None,
    investigation_id: UUID | None = None,
    expires_at: datetime | None = NOW + timedelta(hours=1),
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
        granted_at=NOW,
        override_ask_default=True,
    )


def _request(
    *,
    agent: str = "argus",
    action: CredentialAction = CredentialAction.READ,
    ref: CredentialRef | None = None,
    ttl_seconds: int = 3600,
) -> AccessRequest:
    return AccessRequest(
        id=uuid4(),
        investigation_id=RUN,
        agent=agent,
        credential_ref=ref if ref is not None else _ref(environment="staging"),
        action=action,
        reason="connection saturation may explain the p99 latency",
        requested_ttl_seconds=ttl_seconds,
        requested_at=NOW,
    )


def _broker(audit: AuditLog | None = None) -> tuple[Cerberus, _Ticker]:
    clock = _Ticker()
    return (
        Cerberus(
            grants=GrantBook(),
            leases=LeaseBook(clock=clock),
            audit=audit,
            clock=clock,
        ),
        clock,
    )


# --- the three outcomes -------------------------------------------------------------------


def test_a_standing_grant_produces_a_lease() -> None:
    """The control. A broker that refused everything would pass every refusal
    test below and be indistinguishable from a broken one."""
    broker, _ = _broker()
    broker.grants.register(_grant())

    lease = broker.request_access(_request(), connector="postgres")

    assert lease.connector == "postgres"
    assert lease.investigation_id == RUN
    assert lease.credential_ref.id == CRED_ID


def test_a_deny_refuses_and_does_not_park_anything() -> None:
    """A refusal that also queued the request would put a decision somebody
    already made back in front of them as though it were open."""
    broker, _ = _broker()
    broker.grants.register(_grant(mode=PermissionMode.DENY, expires_at=None))

    with pytest.raises(AccessRefused, match="recorded refusal"):
        broker.request_access(_request(), connector="postgres")

    assert broker.pending() == []


def test_an_unconsidered_request_is_parked_and_visible() -> None:
    """Raising and forgetting would leave the sentence that IS the decision in
    an exception message and nowhere else."""
    broker, _ = _broker()
    request = _request(ref=_ref(environment="prod"))

    with pytest.raises(ApprovalRequired, match="connection saturation") as raised:
        broker.request_access(request, connector="postgres")

    assert raised.value.request.id == request.id
    assert [waiting.id for waiting in broker.pending()] == [request.id]


def test_the_broker_hands_back_a_lease_and_has_no_path_to_a_credential() -> None:
    """Asserted on the surface. An agent holding a Cerberus must not reach a
    secret by any sequence of calls, and that is guaranteed by the plaintext
    side being unreachable from here rather than merely unused."""
    surface = {name for name in dir(Cerberus) if not name.startswith("_")}
    forbidden = {"vault", "redeem", "decrypt", "plaintext", "secret", "value"}

    assert not surface & forbidden, f"the broker exposes {surface & forbidden}"


# --- a human answers ----------------------------------------------------------------------


def test_approving_a_parked_request_makes_the_next_one_succeed() -> None:
    """The whole loop, and the only test that proves the parked request was
    connected to anything."""
    broker, _ = _broker()
    request = _request(ref=_ref(environment="prod"))
    with pytest.raises(ApprovalRequired):
        broker.request_access(request, connector="postgres")

    broker.approve(request.id, by="alex")
    lease = broker.request_access(_request(ref=_ref(environment="prod")), connector="postgres")

    assert lease.credential_ref.id == CRED_ID
    assert broker.pending() == []


def test_an_approval_defaults_to_dying_with_the_run() -> None:
    """The easy path is the narrow one: an approver who wants a standing grant
    has to say so."""
    broker, _ = _broker()
    request = _request(ref=_ref(environment="prod"))
    with pytest.raises(ApprovalRequired):
        broker.request_access(request, connector="postgres")

    grant = broker.approve(request.id, by="alex")

    assert grant.mode is PermissionMode.ALLOW_FOR_INVESTIGATION
    assert grant.investigation_id == RUN
    assert grant.expires_at is None


def test_an_approver_cannot_widen_the_posture_by_accident() -> None:
    """`policy.defaults` runs on the grant the approval produces, so approving
    a production request into a standing grant is refused here too."""
    broker, _ = _broker()
    request = _request(ref=_ref(environment="prod"))
    with pytest.raises(ApprovalRequired):
        broker.request_access(request, connector="postgres")

    with pytest.raises(ValueError, match="outlive every run"):
        broker.approve(
            request.id,
            by="alex",
            mode=PermissionMode.ALLOW_UNTIL,
            expires_at=NOW + timedelta(days=7),
        )


def test_an_agent_cannot_approve_its_own_request() -> None:
    """Self-approval is a gate that logs itself."""
    broker, _ = _broker()
    request = _request(ref=_ref(environment="prod"))
    with pytest.raises(ApprovalRequired):
        broker.request_access(request, connector="postgres")

    with pytest.raises(AccessRefused, match="cannot approve its own"):
        broker.approve(request.id, by="argus")


def test_approving_something_nobody_asked_for_is_refused() -> None:
    """Otherwise permission is created out of a typo."""
    broker, _ = _broker()

    with pytest.raises(AccessRefused, match="is waiting"):
        broker.approve(uuid4(), by="alex")


def test_refusing_a_request_records_the_no_and_clears_the_queue() -> None:
    """A refusal that only removed it would be indistinguishable from an
    approval in the trail, and "we said no at 03:10" is the fact somebody needs
    afterwards."""
    audit = AuditLog(secrets=[])
    broker, _ = _broker(audit)
    request = _request(ref=_ref(environment="prod"))
    with pytest.raises(ApprovalRequired):
        broker.request_access(request, connector="postgres")

    broker.refuse(request.id, by="alex", why="wrong hypothesis, check the pool first")

    assert broker.pending() == []
    assert audit.entries()[-1].event is AuditEvent.DENIED
    assert "wrong hypothesis" in audit.entries()[-1].detail


# --- the lease the broker hands back --------------------------------------------------------


def test_a_short_request_gets_the_short_lease_it_asked_for() -> None:
    """A shorter request is information about how long the credential is
    actually needed, and there is no reason to hand back more."""
    broker, _ = _broker()
    broker.grants.register(_grant())

    lease = broker.request_access(_request(ttl_seconds=30), connector="postgres")

    assert lease.expires_at == NOW + timedelta(seconds=30)


def test_a_long_request_does_not_widen_the_book() -> None:
    """The TTL is a ceiling and never a floor. An agent asking for eight hours
    is asking to widen the setting that bounds every lease in the system, one
    lease at a time."""
    broker, _ = _broker()
    broker.grants.register(_grant())

    lease = broker.request_access(_request(ttl_seconds=8 * 3600), connector="postgres")

    assert lease.expires_at == NOW + broker.leases.ttl


def test_the_lease_never_reaches_past_the_grant() -> None:
    broker, _ = _broker()
    broker.grants.register(_grant(expires_at=NOW + timedelta(seconds=10)))

    lease = broker.request_access(_request(ttl_seconds=3600), connector="postgres")

    assert lease.expires_at == NOW + timedelta(seconds=10)


def test_the_whole_decision_is_in_the_trail() -> None:
    audit = AuditLog(secrets=[])
    broker, _ = _broker(audit)
    broker.grants.register(_grant())

    lease = broker.request_access(_request(), connector="postgres")

    events = [entry.event for entry in audit.entries()]
    assert events == [AuditEvent.REQUESTED, AuditEvent.LEASE_MINTED]
    assert audit.entries()[-1].lease_id == lease.id
    assert "saturation" in audit.entries()[0].detail


def test_a_broker_without_an_audit_log_still_decides() -> None:
    """The trail is a record, not a gate, and confusing the two would make an
    unaudited path a permitted one."""
    broker, _ = _broker(audit=None)

    with pytest.raises(ApprovalRequired):
        broker.request_access(_request(ref=_ref(environment="prod")), connector="postgres")


# --- revocation: the leases are the point ----------------------------------------------------


def _leased() -> tuple[Cerberus, _Ticker, Grant]:
    broker, clock = _broker()
    grant = broker.grants.register(_grant())
    broker.request_access(_request(), connector="postgres")
    return broker, clock, grant


def test_revoking_a_grant_kills_the_leases_already_minted_from_it() -> None:
    """Without this a revocation takes effect in one TTL rather than now:
    redemption checks the lease, deliberately, so producing a credential does
    not depend on a policy lookup being reachable.
    """
    broker, _, grant = _leased()
    (lease,) = broker.leases.live_leases()

    stopped = revoke_grant(grant.id, grants=broker.grants, leases=broker.leases, by="alex", now=NOW)

    assert stopped.grants == 1
    assert stopped.leases == 1
    assert broker.leases.live_leases() == []
    assert broker.leases.current(lease.id) is not None, "the lease was deleted, not revoked"


def test_revoking_one_grant_leaves_another_agents_lease_alone() -> None:
    """The control. A revocation that killed every lease would pass the test
    above and be a break-glass wearing a narrower name."""
    broker, _, grant = _leased()
    other = broker.grants.register(_grant(agent="hermes"))
    broker.request_access(_request(agent="hermes"), connector="postgres")

    revoke_grant(grant.id, grants=broker.grants, leases=broker.leases, by="alex", now=NOW)

    survivors = [
        lease for lease in broker.leases.minted_from(other.id) if broker.leases.live(lease)
    ]
    assert len(survivors) == 1


def test_revoking_an_agent_stops_every_grant_it_holds() -> None:
    """Scoped to the agent, because the reason to reach for this is a
    misbehaving agent - and asking which of its grants to keep is a question
    with no good answer while it is still running."""
    broker, _ = _broker()
    for _ in range(3):
        broker.grants.register(_grant())
    broker.grants.register(_grant(agent="hermes"))

    stopped = revoke_agent("argus", grants=broker.grants, leases=broker.leases, by="alex", now=NOW)

    assert stopped.grants == 3
    assert [grant.revoked_at is None for grant in broker.grants.held_by("hermes")] == [True]


def test_break_glass_kills_a_lease_whose_grant_this_book_never_saw() -> None:
    """A lease minted before a restart, or from a grant since deleted, is
    exactly the one the handle is being pulled for."""
    broker, _ = _broker()
    orphan = broker.leases.mint(
        _grant(),
        investigation_id=RUN,
        connector="postgres",
        action=CredentialAction.READ,
        request_id=uuid4(),
    )
    assert broker.leases.live(orphan)

    stopped = break_glass(
        grants=broker.grants,
        leases=broker.leases,
        by="alex",
        reason="argus is looping on renewals",
        now=NOW,
    )

    assert stopped.grants == 0, "the grant was never registered"
    assert stopped.leases == 1
    assert broker.leases.live_leases() == []


def test_break_glass_does_not_count_leases_that_had_already_expired() -> None:
    """The count is what somebody reads to decide whether the system stopped,
    and counting dead leases inflates it in the direction of reassurance."""
    broker, clock = _broker()
    broker.grants.register(_grant(expires_at=None))
    broker.request_access(_request(ttl_seconds=30), connector="postgres")
    clock.now = NOW + timedelta(minutes=1)

    stopped = break_glass(
        grants=broker.grants, leases=broker.leases, by="alex", reason="drill", now=clock.now
    )

    assert stopped.leases == 0


def test_break_glass_is_recorded_even_when_it_stopped_nothing() -> None:
    """Pulling the handle on an already-quiet system is still an event, and the
    trail is where somebody reconstructs what was happening."""
    audit = AuditLog(secrets=[])
    broker, _ = _broker(audit)

    break_glass(
        grants=broker.grants,
        leases=broker.leases,
        by="alex",
        reason="suspected token exfiltration",
        audit=audit,
        now=NOW,
    )

    entry = audit.entries()[-1]
    assert entry.event is AuditEvent.BREAK_GLASS
    assert "suspected token exfiltration" in entry.detail


def test_a_revocation_reports_grants_and_leases_separately() -> None:
    """ "revoked 3" cannot answer the question anybody asks after pulling the
    handle - three grants with eleven live leases still redeemable is not a
    system that has stopped."""
    broker, _, grant = _leased()

    stopped = revoke_grant(grant.id, grants=broker.grants, leases=broker.leases, by="alex", now=NOW)

    assert str(stopped).startswith("1 grants and 1 leases")


def test_revoking_a_grant_that_was_never_there_stops_nothing() -> None:
    broker, _ = _broker()

    stopped = revoke_grant(uuid4(), grants=broker.grants, leases=broker.leases, by="alex", now=NOW)

    assert (stopped.grants, stopped.leases) == (0, 0)
