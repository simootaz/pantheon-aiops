"""Safe defaults.

Production targets and ALL write actions default to ASK_EACH_TIME and cannot be
set to ALLOW_UNTIL without an explicit override flag on the grant.

The default is the security posture. Anyone can widen it deliberately; nobody
should widen it by accident.

WHERE THE DEFAULT IS ENFORCED
-------------------------------
Twice, and they answer different questions.

`ask_by_default` answers "what happens when no grant covers this request" - the
posture. `refuse_unsafe_grant` answers "may this grant exist at all" - and it
runs when the grant is REGISTERED, not when it is used.

Checking only at use would let an unsafe grant sit in the book looking valid
until the moment it mattered, which is a refusal at 03:00 for a decision
somebody made calmly weeks earlier.

AN UNNAMED ENVIRONMENT IS TREATED AS PRODUCTION
-------------------------------------------------
A grant that names no environment covers every environment, production
included. Reading unset as "not production" would make the widest grant in the
system the one that skips the production check, which inverts the posture
exactly where it costs most.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.contracts.credentials import (
    CredentialAction,
    CredentialRef,
    Grant,
    PermissionMode,
)

#: Environment names that mean production. Matched case-insensitively.
#:
#: A list rather than a pattern, because the interesting mistake is a name
#: nobody anticipated - and an unrecognised name is treated as production
#: anyway, so the list only has to be right about which names are SAFE.
PRODUCTION_NAMES = frozenset({"prod", "production", "prd", "live"})

#: Environment names known not to be production. Everything else - including an
#: environment nobody named - is production for the purposes of this module.
NON_PRODUCTION_NAMES = frozenset(
    {"dev", "development", "staging", "stage", "test", "qa", "sandbox"}
)


class UnsafeGrant(ValueError):
    """A grant that widens the default posture without saying it meant to."""


def is_production(ref: CredentialRef) -> bool:
    """Whether this credential points at production.

    Unset is production. So is any name this module does not recognise: a
    credential scoped to `environment="prod-eu"` is not on either list, and
    guessing wrong in the safe direction costs an approval prompt while
    guessing wrong in the other direction costs a production incident.
    """
    environment = ref.scope.environment
    if environment is None:
        return True
    return environment.strip().lower() not in NON_PRODUCTION_NAMES


def ask_by_default(ref: CredentialRef, action: CredentialAction) -> str | None:
    """Why this access needs a human when no grant covers it, or `None`.

    Returns the REASON rather than a bool, because it is the reason that goes
    in front of the approver - "an agent wants database access" is not a
    decision anybody can make.
    """
    if action is CredentialAction.WRITE:
        return (
            f"{action.value} on {ref.name} changes a system. Every write asks, "
            "whatever the environment - the connector split puts reads and writes "
            "behind separate grants for the same reason."
        )
    if is_production(ref):
        environment = ref.scope.environment or "unnamed, which is read as production"
        return (
            f"{ref.name} is in {environment}. Production reads ask by default; a "
            "standing grant is something somebody chooses, not something a request "
            "arrives already holding."
        )
    return None


def refuse_unsafe_grant(grant: Grant) -> None:
    """Raise `UnsafeGrant` if this grant widens the default without the override.

    Only ALLOW_UNTIL is refused. ALLOW_FOR_INVESTIGATION dies with the run that
    asked for it, so its blast radius is bounded by the reason it was given -
    that is the whole of what the mode means, and it is why it exists as a
    middle setting rather than as a shorter ALLOW_UNTIL.
    """
    if grant.mode is not PermissionMode.ALLOW_UNTIL or grant.override_ask_default:
        return

    reason = ask_by_default(grant.credential_ref, grant.action)
    if reason is None:
        return

    raise UnsafeGrant(
        f"grant {grant.id} is ALLOW_UNTIL and would outlive every run. {reason} Set "
        "override_ask_default to say this was deliberate, or use "
        "ALLOW_FOR_INVESTIGATION, which expires with the run that asked."
    )
