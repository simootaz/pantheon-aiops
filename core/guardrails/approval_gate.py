"""The human-in-the-loop gate: an Action waits here until someone answers.

WHAT AN APPROVAL IS FOR
-------------------------
Not an Action id. **The content of the Action as it was when the approver read
it.** `core/contracts/ui.py` already states the rule - a response "carries no
decision authority of its own; an approval reaching the Approval Gate is
re-validated there against the request it claims to answer" - and this is where
that happens.

The attack it closes is not exotic. Propose a dry run, get it approved, flip
`dry_run` to False, execute. Same id, same approval, entirely different act. So
the request stores a digest of the fields a person would have weighed, and an
approval against a changed Action is refused rather than honoured.

WHAT IS NOT IN THE DIGEST, AND WHY
------------------------------------
`execution_state` and `receipts` change as an Action runs and say nothing about
whether it should. Including them would void an approval the moment execution
began - which reads as a race and is really a digest that included the clock.

TIMEOUT FAILS CLOSED
----------------------
An unanswered request expires. It never becomes approved, and the difference
matters more than it looks: an approval gate whose timeout defaults open is a
delay, not a gate, and the way that is discovered is an action running at 04:00
because nobody was awake to say no.

Expiry is evaluated on READ rather than by a timer. A background sweep would
make "expired" depend on whether the sweep ran, and a gate that answers
differently depending on scheduler pressure is not one anybody can reason about.

SELF-APPROVAL
---------------
The proposer cannot approve. Pantheon proposes as `zeus` or an agent codename,
so this mostly stops an operator wiring the approval endpoint to whatever
proposed the Action - which is exactly what a hurried automation does at three
in the morning.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from core.contracts.action import Action, ApprovalState
from core.guardrails.policy import Decision, Ruling

#: How long a request waits before it expires. Short enough that a forgotten
#: approval does not sit open for a day carrying the authority to change
#: production, long enough for someone to be paged and read it.
DEFAULT_TTL = timedelta(minutes=30)


class ApprovalError(RuntimeError):
    """A response that cannot be honoured, with the reason in the message.

    One exception type rather than several: every case here is "this response is
    not valid for this request", and the caller's next step is the same - tell
    the person why and do not execute.
    """


class Clock(Protocol):
    """Injected so expiry is testable without waiting."""

    def __call__(self) -> datetime: ...


def _now() -> datetime:
    return datetime.now(tz=UTC)


def digest_of(action: Action) -> str:
    """A fingerprint of what an approver would have weighed.

    Deliberately NOT the whole model. `execution_state` and `receipts` change as
    the Action runs and say nothing about whether it should run, so including
    them would void an approval the instant execution started.

    `parameters` is sorted, because `{"replicas": 4}` and the same dict built in
    another order are the same act, and a digest that disagreed would void
    approvals for a reason no human could see.
    """
    body = json.dumps(
        {
            "target": action.target.model_dump(mode="json"),
            "operation": action.operation,
            "parameters": action.parameters,
            "blast_radius": action.blast_radius.value,
            "dry_run": action.dry_run,
            "rollback": action.rollback,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    """One Action waiting for a person."""

    id: UUID
    action_id: UUID
    action_digest: str
    proposed_by: str
    ruling: Ruling
    opened_at: datetime
    expires_at: datetime

    #: Set once, when someone answers. `None` while waiting.
    answered_at: datetime | None = None
    answered_by: str | None = None
    approved: bool | None = None
    reason: str = ""

    def state(self, *, now: datetime) -> ApprovalState:
        """Where this request stands, evaluated against the clock on read.

        A timer-driven state would depend on whether a sweep ran. This cannot.

        AN APPROVAL DECAYS; A REJECTION DOES NOT
        ------------------------------------------
        The asymmetry is deliberate. An approval carries authority to change a
        real system, and authority granted for an incident at noon should not
        still be spendable at eight in the evening - the world has moved and
        nobody re-read it. A rejection carries no authority, so there is nothing
        to expire, and decaying it into EXPIRED would lose the fact that a
        person looked and said no.

        The first version of this returned APPROVED regardless of the clock,
        while `may_execute` documented that it checked expiry. The documentation
        was right about what should happen and the code was not.

        ONE DEADLINE, AND WHAT IT DOES NOT DISTINGUISH
        ------------------------------------------------
        `expires_at` is the deadline for the whole thing: answer by then, and
        execute by then. "How long we wait for an answer" and "how long an
        approval stays spendable after it is granted" are genuinely different
        durations, and collapsing them into one is a simplification rather than
        a design. Splitting them is a change worth making when something needs
        the difference; inventing two numbers now would be guessing at both.
        """
        if self.approved is False:
            return ApprovalState.REJECTED
        if now >= self.expires_at:
            return ApprovalState.EXPIRED
        if self.approved is True:
            return ApprovalState.APPROVED
        return ApprovalState.PENDING

    def as_dict(self) -> dict[str, object]:
        """For the API and the audit trail. No credential ever passes here."""
        return {
            "id": str(self.id),
            "action_id": str(self.action_id),
            "proposed_by": self.proposed_by,
            "opened_at": self.opened_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "answered_by": self.answered_by,
            "reason": self.reason,
            "rule": self.ruling.rule,
        }


@dataclass
class ApprovalGate:
    """Where requests live between being opened and being answered.

    In-process for now. The store is a plain dict rather than a Protocol
    because there is exactly one implementation and inventing a seam for a
    second that does not exist is how an interface ends up shaped by nothing.
    Phase 4's approvals API is what will need persistence, and it will need a
    different shape than a guess made here.
    """

    ttl: timedelta = DEFAULT_TTL
    clock: Clock = field(default_factory=lambda: _now)
    _requests: dict[UUID, ApprovalRequest] = field(default_factory=dict)

    def open_request(self, action: Action, ruling: Ruling) -> ApprovalRequest:
        """Start waiting for a person. Only valid for a ruling that asked for one.

        Named `open_request` rather than `open`: a test module calling
        `gate.open(...)` is indistinguishable, to a static scan, from one
        reading a file directly - and `test_mechanism_helper_is_used.py`
        forbids the latter. Two concepts sharing a spelling is how a guard
        over one starts firing on the other, the same way `max_tokens` did.

        An ALLOW does not need a gate and a DENY cannot be approved past, so
        opening a request for either is a caller bug. Refusing here rather than
        accepting it stops a denied Action from acquiring an approval that makes
        it look permitted.
        """
        if ruling.decision is not Decision.REQUIRE_APPROVAL:
            raise ApprovalError(
                f"ruling is {ruling.decision.value} ({ruling.rule}), so there is nothing "
                "to approve. Opening a request for an ALLOW invents a gate that was not "
                "asked for; opening one for a DENY manufactures a way past it."
            )

        now = self.clock()
        request = ApprovalRequest(
            id=uuid4(),
            action_id=action.id,
            action_digest=digest_of(action),
            proposed_by=action.proposed_by,
            ruling=ruling,
            opened_at=now,
            expires_at=now + self.ttl,
        )
        self._requests[request.id] = request
        return request

    def get(self, request_id: UUID) -> ApprovalRequest | None:
        return self._requests.get(request_id)

    def state(self, request_id: UUID) -> ApprovalState:
        """The state, or a refusal. An unknown id is not `PENDING`.

        Returning PENDING for something that was never opened would make a typo
        indistinguishable from a request nobody has answered yet.
        """
        request = self._requests.get(request_id)
        if request is None:
            raise ApprovalError(f"no approval request {request_id}")
        return request.state(now=self.clock())

    def respond(
        self,
        request_id: UUID,
        action: Action,
        *,
        approver: str,
        approve: bool,
        reason: str = "",
    ) -> ApprovalRequest:
        """Record an answer, after re-validating it against what was asked.

        The Action is passed back in rather than looked up, because the caller
        is about to execute *that object* and the digest has to be taken from
        the thing that will run - not from a stored copy that may have diverged
        from it.
        """
        request = self._requests.get(request_id)
        if request is None:
            raise ApprovalError(f"no approval request {request_id}")

        now = self.clock()
        current = request.state(now=now)
        if current is not ApprovalState.PENDING:
            raise ApprovalError(
                f"request {request_id} is already {current.value}. An answer stands: a "
                "second response would let a rejection be overturned by whoever clicked "
                "last, and an expired request would come back to life."
            )

        if action.id != request.action_id:
            raise ApprovalError(
                f"request {request_id} is for action {request.action_id}, not {action.id}"
            )

        if digest_of(action) != request.action_digest:
            raise ApprovalError(
                f"action {action.id} has changed since approval was requested, so this "
                "response answers a different act. Propose it again - an approval is "
                "for what the approver read, not for an id."
            )

        if approver == request.proposed_by:
            raise ApprovalError(
                f"{approver} proposed this action and cannot approve it. Two people, or "
                "the gate is a formality that logs one person agreeing with themselves."
            )

        answered = ApprovalRequest(
            id=request.id,
            action_id=request.action_id,
            action_digest=request.action_digest,
            proposed_by=request.proposed_by,
            ruling=request.ruling,
            opened_at=request.opened_at,
            expires_at=request.expires_at,
            answered_at=now,
            answered_by=approver,
            approved=approve,
            reason=reason,
        )
        self._requests[request.id] = answered
        return answered

    def pending(self) -> list[ApprovalRequest]:
        """Everything still waiting, oldest first. Expired ones are not pending."""
        now = self.clock()
        waiting = [
            request
            for request in self._requests.values()
            if request.state(now=now) is ApprovalState.PENDING
        ]
        waiting.sort(key=lambda request: request.opened_at)
        return waiting


def may_execute(request: ApprovalRequest, action: Action, *, now: datetime | None = None) -> bool:
    """The single question an executor asks. True only for a live approval.

    Every clause is a separate way this could be wrong, and all four are checked
    at the moment of execution rather than trusted from earlier:

    * the request was approved, not merely answered;
    * it has not expired since;
    * it is for this Action;
    * the Action has not changed since it was read.

    A caller that checks only `approved` has an approval that outlives both the
    timeout and the content it was given for.
    """
    moment = now if now is not None else _now()
    return (
        request.state(now=moment) is ApprovalState.APPROVED
        and request.action_id == action.id
        and request.action_digest == digest_of(action)
    )


#: Re-exported so an executor needs one import to ask the whole question.
__all__ = [
    "DEFAULT_TTL",
    "ApprovalError",
    "ApprovalGate",
    "ApprovalRequest",
    "digest_of",
    "may_execute",
]
