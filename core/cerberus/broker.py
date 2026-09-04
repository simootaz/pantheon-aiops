"""Cerberus entrypoint - the only module an agent may touch.

Takes an AccessRequest, evaluates policy, routes to the Approval Gate when
there is no standing grant, and mints a Lease bound to one connector and one
investigation.

It returns a Lease. It never returns plaintext, and it has no code path that
could: plaintext lives behind core.cerberus.redemption, which agents cannot
import (enforced by tests/unit/test_credential_safety.py).

THE GATE FOR CREDENTIALS IS THE GRANT, NOT `core.guardrails.approval_gate`
---------------------------------------------------------------------------
That gate binds an approval to a digest of an `Action`'s content, and an
AccessRequest is not an Action - it has no target, no parameters and no
rollback. Routing through it would mean fabricating an Action whose digest
covered fields that do not exist, which is a gate with nothing underneath it.

So an ASK verdict parks the request here and raises `ApprovalRequired`. A human
answers by issuing a Grant, which IS the approval - `Grant.granted_by` is the
approver, and `policy.defaults` refuses one that widens the posture silently.
The same property holds as in the other gate: the approval is for the content
somebody read, because the request is immutable and the grant it produces names
the credential and action it was given for.

WHY THE REQUEST IS PARKED RATHER THAN JUST REFUSED
----------------------------------------------------
Raising and forgetting would leave "argus wanted the production database at
03:04, to test whether connection saturation explains the latency" in an
exception message and nowhere else. That sentence is the decision. `pending()`
is what puts it in front of somebody.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from core.cerberus.audit.log import AuditLog
from core.cerberus.lease import LeaseBook
from core.cerberus.policy import evaluate
from core.cerberus.policy.grants import GrantBook
from core.cerberus.policy.modes import Answer, Verdict
from core.contracts.credentials import (
    AccessRequest,
    AuditEvent,
    Grant,
    Lease,
    PermissionMode,
)


class AccessRefused(RuntimeError):
    """Policy said no, and the message says which no.

    Distinct from `ApprovalRequired` because they lead to opposite next steps:
    one is a decision already made, the other is a decision nobody has made
    yet. An agent that treated them alike would either wait for an approver who
    is never coming, or ask again about something already refused.
    """


class ApprovalRequired(RuntimeError):
    """Nobody has granted this yet. The request is parked and visible."""

    def __init__(self, message: str, *, request: AccessRequest) -> None:
        super().__init__(message)
        self.request = request


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass
class Cerberus:
    """The broker. One object an agent holds, and it hands back leases.

    The vault is deliberately absent from this class. An agent holding a
    Cerberus must not be able to reach a credential through it by any sequence
    of calls, and the surest way to guarantee that is for the plaintext side to
    be unreachable from here rather than merely unused.
    """

    grants: GrantBook = field(default_factory=GrantBook)
    leases: LeaseBook = field(default_factory=LeaseBook)
    audit: AuditLog | None = None
    clock: Callable[[], datetime] = field(default_factory=lambda: _now)
    _pending: dict[UUID, AccessRequest] = field(default_factory=dict)

    def request_access(self, request: AccessRequest, *, connector: str) -> Lease:
        """Evaluate, then mint - or refuse, or park the request for a human.

        `connector` is who will redeem the lease, supplied here rather than
        read off the request: the agent asks for a capability, and which
        connector serves it is not the agent's decision to make.
        """
        now = self.clock()
        self._record(AuditEvent.REQUESTED, request, request.reason)

        verdict = evaluate(request, grants=self.grants, now=now)

        if verdict.answer is Answer.DENY:
            self._record(AuditEvent.DENIED, request, verdict.why)
            raise AccessRefused(verdict.why)

        if verdict.answer is Answer.ASK:
            self._pending[request.id] = request
            self._record(AuditEvent.APPROVAL_REQUESTED, request, verdict.why)
            raise ApprovalRequired(
                f"{verdict.why} Request {request.id} is waiting: {request.agent} wants "
                f"{request.action.value} on {request.credential_ref.name} to test - "
                f"{request.reason}",
                request=request,
            )

        grant = self.grants.get(verdict.grant_id) if verdict.grant_id else None
        if grant is None:  # pragma: no cover - an ALLOW always names its grant
            raise AccessRefused(f"verdict allowed but named no grant: {verdict.why}")

        return self._mint(request, grant, connector=connector, verdict=verdict)

    def approve(
        self,
        request_id: UUID,
        *,
        by: str,
        mode: PermissionMode = PermissionMode.ALLOW_FOR_INVESTIGATION,
        expires_at: datetime | None = None,
    ) -> Grant:
        """A human answers a parked request by granting it.

        The default is ALLOW_FOR_INVESTIGATION: permission that dies with the
        run that asked. An approver who wants a standing grant says so, and
        `policy.defaults` refuses an ALLOW_UNTIL on a production or write
        target without an explicit override - so the easy path is the narrow
        one.

        The approver cannot be the requesting agent. Self-approval would make
        the gate a formality that logs itself.
        """
        request = self._pending.get(request_id)
        if request is None:
            raise AccessRefused(
                f"no request {request_id} is waiting. It was answered already, or it "
                "was never parked - and approving one that nobody made would create "
                "permission out of a typo."
            )
        if by == request.agent:
            raise AccessRefused(
                f"{by} cannot approve its own request. Self-approval is a gate that logs itself."
            )

        grant = self.grants.register(
            Grant(
                id=request.id,
                agent=request.agent,
                credential_ref=request.credential_ref,
                action=request.action,
                mode=mode,
                investigation_id=(
                    request.investigation_id
                    if mode is PermissionMode.ALLOW_FOR_INVESTIGATION
                    else None
                ),
                expires_at=expires_at if mode is PermissionMode.ALLOW_UNTIL else None,
                granted_by=by,
                granted_at=self.clock(),
            )
        )
        del self._pending[request_id]
        self._record(AuditEvent.GRANTED, request, f"granted by {by} as {mode.value}")
        return grant

    def refuse(self, request_id: UUID, *, by: str, why: str) -> None:
        """A human answers a parked request by refusing it.

        Recorded, and the request leaves the queue. A refusal that only removed
        it would be indistinguishable from an approval in the trail, and "we
        said no to this at 03:10" is the fact somebody needs afterwards.
        """
        request = self._pending.pop(request_id, None)
        if request is None:
            raise AccessRefused(f"no request {request_id} is waiting")
        self._record(AuditEvent.DENIED, request, f"refused by {by}: {why}")

    def pending(self) -> list[AccessRequest]:
        """Requests waiting for a person, oldest first."""
        return sorted(self._pending.values(), key=lambda request: request.requested_at)

    def _mint(
        self,
        request: AccessRequest,
        grant: Grant,
        *,
        connector: str,
        verdict: Verdict,
    ) -> Lease:
        """Issue the lease, bounded by what the agent asked for.

        The requested TTL can only shorten. An agent asking for eight hours
        gets the book's TTL; an agent asking for thirty seconds gets thirty
        seconds, because a shorter request is information about how long the
        credential is actually needed and there is no reason to hand back more.

        The capping is `LeaseBook.mint`'s, not repeated here. A `min` in both
        places would be two guards where one suffices, and neither could be
        tested alone - the plant that removed this one changed nothing, which
        is how it was found.
        """
        lease = self.leases.mint(
            grant,
            investigation_id=request.investigation_id,
            connector=connector,
            action=request.action,
            request_id=request.id,
            ttl=timedelta(seconds=request.requested_ttl_seconds),
        )
        self._record(
            AuditEvent.LEASE_MINTED,
            request,
            f"{verdict.why}; lease expires {lease.expires_at.isoformat()}",
            lease_id=lease.id,
        )
        return lease

    def _record(
        self,
        event: AuditEvent,
        request: AccessRequest,
        detail: str,
        *,
        lease_id: UUID | None = None,
    ) -> None:
        if self.audit is None:
            return
        self.audit.append(
            event,
            actor=request.agent,
            investigation_id=request.investigation_id,
            credential_ref=request.credential_ref,
            action=request.action,
            lease_id=lease_id,
            detail=detail,
        )
