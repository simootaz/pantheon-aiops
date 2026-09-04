"""Permission modes: Deny, Ask each time, Allow for this investigation, Allow until.

ALLOW_FOR_INVESTIGATION expires with the run that requested it, so a broad
approval cannot outlive the reason it was given.

WHAT THIS MODULE ANSWERS, AND WHAT IT DOES NOT
------------------------------------------------
One grant, one request, one moment: what does this grant's MODE say? It does
not ask whether the grant is for the right agent, credential, action or scope -
`grants.py` has already established that, and asking again here would mean two
modules that must agree about matching, which is one module too many.

EXPIRY IS ANSWERED ON READ
----------------------------
The same choice as the lease book, the approval gate and the capability matrix.
A sweep would make "expired" depend on whether the sweep ran, and a credential
system that answers differently under scheduler pressure is not one anybody can
reason about at 03:00.

A DEAD GRANT ANSWERS `ASK`, NOT `DENY`
----------------------------------------
An expired or revoked grant is the absence of permission, not a refusal of it.
Answering DENY would make a grant that lapsed on Friday indistinguishable from
one somebody deliberately set to DENY, and those lead to opposite
conversations: one is "renew it", the other is "no, and here is why".

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from core.contracts.credentials import Grant, PermissionMode


class Answer(StrEnum):
    """What a grant says. Three outcomes, and they are not interchangeable."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Verdict:
    """An `Answer` and the sentence explaining it.

    Every verdict names its reason. At 03:00 the question is never whether the
    answer was no; it is *which* no - a DENY somebody wrote, a grant that
    lapsed, or a mode that always asks.
    """

    __slots__ = ("answer", "grant_id", "why")

    def __init__(self, answer: Answer, why: str, *, grant_id: UUID | None = None) -> None:
        self.answer = answer
        self.why = why
        self.grant_id = grant_id

    @property
    def allowed(self) -> bool:
        """True only for ALLOW. ASK is not permission; it is a question."""
        return self.answer is Answer.ALLOW

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Verdict({self.answer.value}, {self.why!r})"


def answer(grant: Grant, *, investigation_id: UUID, now: datetime) -> Verdict:
    """What this grant says about a request, at this moment.

    DENY is checked first and is not conditional on the grant being live. A
    revoked DENY is still a recorded refusal, and reading it as "no permission"
    would let the next broad ALLOW answer instead - which turns deleting a deny
    into a way of granting access.
    """
    if grant.mode is PermissionMode.DENY:
        return Verdict(
            Answer.DENY,
            f"grant {grant.id} is a DENY for {grant.agent} on "
            f"{grant.credential_ref.name}. A recorded refusal, not an absence of one.",
            grant_id=grant.id,
        )

    if grant.revoked_at is not None:
        return Verdict(
            Answer.ASK,
            f"grant {grant.id} was revoked at {grant.revoked_at.isoformat()}. Permission "
            "nobody currently holds - ask for it again rather than assume it stands.",
            grant_id=grant.id,
        )

    if grant.expires_at is not None and now >= grant.expires_at:
        return Verdict(
            Answer.ASK,
            f"grant {grant.id} expired at {grant.expires_at.isoformat()}. A lapsed grant "
            "is the absence of permission, not a refusal of it.",
            grant_id=grant.id,
        )

    if grant.mode is PermissionMode.ASK_EACH_TIME:
        return Verdict(
            Answer.ASK,
            f"grant {grant.id} is ASK_EACH_TIME. It records that this agent may be "
            "given this access, not that it currently has it.",
            grant_id=grant.id,
        )

    if grant.mode is PermissionMode.ALLOW_FOR_INVESTIGATION:
        if grant.investigation_id != investigation_id:
            return Verdict(
                Answer.ASK,
                f"grant {grant.id} is scoped to investigation {grant.investigation_id} and "
                f"this request is for {investigation_id}. A broad approval cannot outlive "
                "the reason it was given - that is the whole of what the mode means.",
                grant_id=grant.id,
            )
        return Verdict(
            Answer.ALLOW,
            f"grant {grant.id} allows {grant.agent} for this investigation",
            grant_id=grant.id,
        )

    return Verdict(
        Answer.ALLOW,
        f"grant {grant.id} allows {grant.agent} until "
        f"{grant.expires_at.isoformat() if grant.expires_at else 'revoked'}",
        grant_id=grant.id,
    )
