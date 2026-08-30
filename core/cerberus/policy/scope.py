"""Scoping: server, service, environment.

A grant for one scope must never satisfy a request in another - most
importantly, a staging grant must never satisfy a production request.

UNSET ON A GRANT IS "ANY". UNSET ON A REQUEST IS "UNKNOWN".
------------------------------------------------------------
That asymmetry is the whole module. A grant naming no environment is a
deliberate wildcard - somebody wrote it that way. A request naming no
environment is a question nobody answered, and it might be production.

So a narrow grant does not satisfy a vague request. Treating unknown as
matching would mean a staging grant answers a request that never said where it
was pointing, which is the exact failure this module exists to prevent - and it
would fail silently, because the request that slipped through looks identical
to one that legitimately matched.

SPECIFICITY ORDERS THE MATCHES
--------------------------------
When several grants cover a request, the narrowest wins. A grant naming a
server was written about that server; a wildcard was written about everything,
including things nobody had in mind yet.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.contracts.credentials import CredentialScope

#: The scope fields, in the order specificity ties are broken. Server first: it
#: is the narrowest thing a grant can name.
FIELDS = ("server", "service", "environment")


def covers(grant_scope: CredentialScope, request_scope: CredentialScope) -> bool:
    """Whether a grant written for `grant_scope` answers a request in `request_scope`.

    Field by field. A `None` on the grant is a wildcard and covers anything. A
    value on the grant must be matched exactly by the request, and a `None` on
    the REQUEST does not match it - unknown is not a wildcard.
    """
    for field in FIELDS:
        wanted = getattr(grant_scope, field)
        if wanted is None:
            continue
        if getattr(request_scope, field) != wanted:
            return False
    return True


def specificity(scope: CredentialScope) -> int:
    """How narrow a scope is. Higher is narrower.

    A plain count of named fields. Weighting them - server worth more than
    environment, say - would encode an opinion about which axis matters, and
    the axes are not comparable: `server=db-01` and `environment=prod` are
    narrow in different directions and neither contains the other.
    """
    return sum(1 for field in FIELDS if getattr(scope, field) is not None)


def describe(scope: CredentialScope) -> str:
    """A scope, for a refusal message. At 03:00 the question is which scope."""
    named = [f"{field}={getattr(scope, field)}" for field in FIELDS if getattr(scope, field)]
    return ", ".join(named) if named else "unscoped"
