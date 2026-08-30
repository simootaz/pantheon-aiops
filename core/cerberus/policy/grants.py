"""Grant matching: agent, target, action, scope, TTL.

Read and write are separate grants. A read grant never satisfies a write
request, mirroring the connector split between internal/readonly and
internal/write.

MATCHING IS EXACT, SELECTION IS ORDERED
-----------------------------------------
Matching asks which grants are *about* this request: same agent, same
credential, same action, and a scope that covers it. Selection asks which of
them ANSWERS, and the order is deliberate:

1. **Any DENY wins**, however broad, and whether or not it is still live.
2. Otherwise the narrowest scope wins - a grant naming a server was written
   about that server, a wildcard was written about everything.
3. Ties go to the most recently granted, because that is the decision somebody
   made last.

Deny-first is the part worth defending. A narrow ALLOW beating a broad DENY
would mean an operator adding a deny has to also find and delete every allow
that could outrank it - revocation becomes a search problem, which is precisely
the thing nobody can do at 03:00 and precisely why break-glass exists.

NO GRANT MATCHING IS NOT THE SAME AS NO GRANT ANSWERING
---------------------------------------------------------
Both end in ASK, and they say different things: one is "nobody has considered
this", the other is "somebody considered it and wrote ASK_EACH_TIME". The
verdict carries which.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from core.cerberus.policy import scope as scoping
from core.cerberus.policy.defaults import ask_by_default, refuse_unsafe_grant
from core.cerberus.policy.modes import Answer, Verdict, answer
from core.contracts.credentials import AccessRequest, Grant


@dataclass
class GrantBook:
    """Every standing grant this process knows about.

    In-process, like the rest of Phase 3's stores. Persisting it is a change of
    container: nothing here is a secret, only statements about who may reach
    one.
    """

    _grants: dict[UUID, Grant] = field(default_factory=dict)

    def register(self, grant: Grant) -> Grant:
        """Record a grant, refusing one that widens the default silently.

        Checked here rather than at use. An unsafe grant sitting in the book
        looking valid until the moment it mattered is a refusal at 03:00 for a
        decision somebody made calmly weeks earlier.
        """
        refuse_unsafe_grant(grant)
        self._grants[grant.id] = grant
        return grant

    def get(self, grant_id: UUID) -> Grant | None:
        return self._grants.get(grant_id)

    def all(self) -> list[Grant]:
        """Every grant, revoked ones included. Revoked is a state, not a deletion."""
        return sorted(self._grants.values(), key=lambda grant: grant.granted_at)

    def held_by(self, agent: str) -> list[Grant]:
        return [grant for grant in self.all() if grant.agent == agent]

    def mark_revoked(self, grant_id: UUID, *, at: datetime) -> bool:
        """Set `revoked_at`. Returns whether there was a grant to revoke.

        Revoking rather than deleting, so the trail keeps the shape of what was
        permitted. `revocation.py` is what callers use; this is the mechanism.
        """
        known = self._grants.get(grant_id)
        if known is None or known.revoked_at is not None:
            return False
        self._grants[grant_id] = known.model_copy(update={"revoked_at": at})
        return True

    def matching(self, request: AccessRequest) -> list[Grant]:
        """Every grant ABOUT this request, unordered by relevance.

        Action is compared exactly. A read grant satisfying a write request is
        the single most consequential widening this module could permit, and it
        would happen through an `in` where an `is` belonged.
        """
        return [
            grant
            for grant in self._grants.values()
            if grant.agent == request.agent
            and grant.credential_ref.id == request.credential_ref.id
            and grant.action is request.action
            and scoping.covers(grant.credential_ref.scope, request.credential_ref.scope)
        ]

    def evaluate(self, request: AccessRequest, *, now: datetime) -> Verdict:
        """What the book says about this request, and why."""
        candidates = self.matching(request)

        if not candidates:
            reason = ask_by_default(request.credential_ref, request.action)
            return Verdict(
                Answer.ASK,
                reason
                or (
                    f"no grant covers {request.agent} reading {request.credential_ref.name} "
                    f"({scoping.describe(request.credential_ref.scope)}). Nobody has "
                    "considered this access, which is a question rather than a refusal."
                ),
            )

        verdicts = [
            (grant, answer(grant, investigation_id=request.investigation_id, now=now))
            for grant in candidates
        ]

        for _, verdict in verdicts:
            if verdict.answer is Answer.DENY:
                return verdict

        # Narrowest first, then most recent. A narrow ASK_EACH_TIME outranking a
        # broad ALLOW is intended: somebody wrote that one about this target.
        # `granted_at` breaks the remaining tie, because two grants of equal
        # scope are two decisions and the later one was made knowing the earlier.
        verdicts.sort(
            key=lambda pair: (
                scoping.specificity(pair[0].credential_ref.scope),
                pair[0].granted_at,
            ),
            reverse=True,
        )
        return verdicts[0][1]
