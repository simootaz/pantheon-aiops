"""FastAPI dependencies for authentication, tenant scoping and RBAC.

WHY THIS EXISTS AT ALL
------------------------
`POST /approvals/{id}` took the approver's name **from the request body**. The
approval gate then checked that the approver was not the proposer - against a
string the caller had just chosen. Every property that gate enforces rested on
the honesty of whoever was calling it.

So the one rule here is: **identity comes from the credential, never from the
payload.** A body field is a claim; a verified token is something the server
established. Nothing downstream can tell the two apart once they are both a
`str`, which is why the type has to differ all the way to the call site - the
routers take a `Principal`, and there is no constructor for one that a request
body can reach.

TOKENS, NOT JWTs
------------------
No signing library and no session store. Tokens are opaque strings configured
against a subject and a set of roles, compared in constant time.

That is a deliberate stopping point rather than a first step: a JWT here would
need key distribution, rotation and revocation to be worth more than this, and
half of that is Phase 4 work in front of a real identity provider. What is
built is small enough to be entirely correct.

THE DEFAULT THAT WOULD HAVE BEEN CATASTROPHIC
-----------------------------------------------
With no tokens configured, the obvious implementation authenticates nobody -
and the obvious *bug* is that it authenticates everybody, because an empty
credential matches an unset expectation. `_principals` refuses to authenticate
against an empty table, and production refuses to start without one.

Open mode is a separate, named state (`AuthMode.NONE`), not the absence of
configuration. An absence is ambiguous; a declaration is not.

WHAT IS NOT GATED YET
-----------------------
Only `/approvals` requires a principal. The read endpoints - investigations,
agents, providers, health - are open, and that is stated rather than implied:
they disclose what the system found, which is a real exposure, and closing it
is a deployment decision that belongs with the identity provider in Phase 4.
The endpoint that *decides* something is gated now because its own guarantees
were resting on nothing.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from core.config import Environment, get_settings


class Role(StrEnum):
    """What a principal may do. Four, and each earns its place.

    Not a permission per endpoint. A role per endpoint is a role nobody can
    reason about, and the question an operator actually asks is "may this
    person approve a production change", not "may this person POST here".
    """

    #: Read what the system found. The floor.
    VIEWER = "viewer"
    #: Start an investigation, propose an Action.
    OPERATOR = "operator"
    #: Answer an approval request. Distinct from OPERATOR on purpose: the
    #: separation between proposing and approving is the whole point of the
    #: gate, and one role holding both makes it a formality.
    APPROVER = "approver"
    #: Break-glass, rotate a master key, revoke every grant. The role that
    #: should be held by nobody most of the time.
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """Who the caller is, as established by the server.

    Frozen, and constructed only by `_principals`. A router that takes one of
    these is holding an identity the server verified - which is a different
    thing from a name in a payload, and the type is what keeps them different.
    """

    subject: str
    roles: frozenset[Role]

    def holds(self, *required: Role) -> bool:
        """Whether this principal holds any of the named roles.

        ADMIN is not a wildcard. An admin who should be able to approve is
        given APPROVER as well - implicit inheritance means the set of people
        who can approve is not the set of people listed as approvers, and that
        is exactly the question an audit asks.
        """
        return bool(self.roles & set(required))


class AuthMisconfigured(RuntimeError):
    """Auth cannot be enforced as configured, so nothing is served."""


def _parse(raw: str) -> dict[str, Principal]:
    """`subject:role,role=token;subject:role=token` into token -> principal.

    Every failure here is fatal rather than skipped. A malformed entry that
    was ignored would silently reduce the set of people who can approve, and
    the symptom - one person's token stops working - reads as that person's
    problem rather than as a configuration error.
    """
    table: dict[str, Principal] = {}
    for entry in (part.strip() for part in raw.split(";")):
        if not entry:
            continue
        identity, separator, token = entry.partition("=")
        if not separator or not token:
            raise AuthMisconfigured(f"token entry {identity!r} has no '=token' part")

        subject, _, role_names = identity.partition(":")
        if not subject.strip():
            raise AuthMisconfigured(f"token entry {entry.split('=')[0]!r} names no subject")

        try:
            roles = frozenset(Role(name.strip()) for name in role_names.split(",") if name.strip())
        except ValueError as unknown:
            raise AuthMisconfigured(
                f"{subject} is given a role that does not exist: {unknown}. Known "
                f"roles are {', '.join(role.value for role in Role)}."
            ) from unknown

        if not roles:
            raise AuthMisconfigured(
                f"{subject} has a token and no roles, so it can authenticate and do "
                "nothing. That is a configuration error and not a read-only account - "
                f"say {Role.VIEWER.value} if that is what was meant."
            )
        if token in table:
            raise AuthMisconfigured(
                f"the same token is configured for {table[token].subject} and {subject}. "
                "An ambiguous identity would let one of them act as the other, and the "
                "trail would name the wrong person."
            )
        table[token] = Principal(subject=subject.strip(), roles=roles)
    return table


@lru_cache(maxsize=1)
def _principals() -> dict[str, Principal]:
    """The configured token table, parsed once.

    Cached because it is read on every request and cannot change without a
    restart - the same reason `get_settings` is cached. `_principals.cache_clear()`
    is what a test calls after changing the environment.
    """
    settings = get_settings()
    raw = settings.api.tokens
    table = _parse(raw.get_secret_value()) if raw is not None else {}

    if not table and settings.env is Environment.PRODUCTION:
        raise AuthMisconfigured(
            "PANTHEON_ENV=production with no PANTHEON_API_TOKENS. An empty table "
            "authenticates nobody, which is correct - but a deployment that meant to "
            "configure tokens and did not would find that out through a support "
            "ticket, so it is refused at startup instead."
        )
    return table


def _bearer(request: Request) -> str | None:
    """The token from `Authorization: Bearer <token>`, or `None`.

    The scheme is checked. Accepting a bare `Authorization: <token>` would mean
    a Basic-auth header, whose value is a base64 blob, could be compared
    against a token - and a comparison that can never succeed is a login that
    fails for a reason nobody can find.
    """
    header = request.headers.get("Authorization")
    if header is None:
        return None
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return token.strip() or None


def authenticate(request: Request) -> Principal:
    """The caller, verified. Raises 401 when they are not.

    The comparison is `hmac.compare_digest` and not `==`. A `==` on a secret
    returns as soon as two bytes differ, so the time it takes is a measurement
    of how much of the token was right - which turns guessing a token from an
    exhaustive search into a per-character one.

    Every failure gives the same message. "unknown token" and "no token" are
    different facts and telling them apart tells an attacker which half to work
    on.
    """
    table = _principals()
    presented = _bearer(request)

    if presented is not None:
        for token, principal in table.items():
            if hmac.compare_digest(token, presented):
                return principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="a valid bearer token is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require(*roles: Role) -> Any:
    """A dependency demanding any of `roles`.

    Used as `Annotated[Principal, require(Role.APPROVER)]` rather than as a
    parameter default. The annotated form is what lets the router's parameter
    be typed `Principal` truthfully - a default would have to be cast, and a
    cast here would be a lie about the one type whose distinctness is the
    module's entire point.

    Returns the `Principal`, so a router that needs the identity does not
    authenticate twice - and more importantly cannot end up with a *different*
    identity for the check and for the record.
    """
    if not roles:  # pragma: no cover - guarded by test
        raise AuthMisconfigured(
            "require() with no roles admits every authenticated caller, which is a "
            "check that cannot fail. Name the roles, or use `authenticate` directly "
            "to say that any principal will do."
        )

    def _dependency(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        if not principal.holds(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"{principal.subject} holds "
                    f"{', '.join(sorted(role.value for role in principal.roles)) or 'no roles'}; "
                    f"this needs one of {', '.join(sorted(role.value for role in roles))}"
                ),
            )
        return principal

    return Depends(_dependency)
