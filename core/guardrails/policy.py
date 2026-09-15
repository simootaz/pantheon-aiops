"""Deciding whether an Action may run, needs a human, or must not run at all.

WHAT THIS IS, AND WHAT ENFORCES IT
------------------------------------
A decision, not a gate. `evaluate()` reads an Action and returns a `Ruling`;
something else has to honour it. The *physical* boundary is still the connector
read/write split - an agent that cannot reach a write tool is safe by
construction, and this layer exists for the actions that genuinely need to run.

THE DEFAULT IS A HUMAN, NOT A YES
-----------------------------------
Rules are ordered and the first match wins, and the last rule is
`REQUIRE_APPROVAL`. An operation nobody has classified gets an approver rather
than permission - the opposite ordering means every capability added after this
file was written is allowed until someone notices.

That makes the allow-list deliberately tiny: an Action that changes nothing, and
a dry run. Everything else is a person's decision, which is the entire point of
the phase this belongs to.

WHY A RULING CARRIES ITS RULE
-------------------------------
"Denied" with no rule named is unauditable. At three in the morning the question
is not whether the system said no, it is *which* no - a blast radius the
operator can argue with, or an execution state that means this already ran. Two
very different next steps, and a bare verdict tells them apart for nobody.

WHAT IT DOES NOT DECIDE
-------------------------
Who may approve, and for how long: that is `approval_gate.py`. Whether a
connector can even perform the operation: that is the connector's declaration.
Whether the credentials exist: Cerberus. This answers one question.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.config import Environment, get_settings
from core.contracts.action import Action, BlastRadius, ExecutionState


class Decision(StrEnum):
    """What the policy says about one Action."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


#: Blast radii nobody may approve their way past in production without the
#: break-glass path. A cluster-wide change during an incident is the one most
#: likely to turn a degraded service into an outage, and an approval prompt at
#: three in the morning is not the moment to weigh that.
#:
#: `core/cerberus/policy/revocation.py` is where break-glass lives. It is a stub,
#: so today this is a hard deny - stated rather than softened, because a deny
#: that can be bypassed by a flag nobody implemented is a deny in name only.
IRREVERSIBLE_IN_PRODUCTION: frozenset[BlastRadius] = frozenset(
    {BlastRadius.CLUSTER, BlastRadius.MULTI_CLUSTER}
)

#: Radii that change nothing outside themselves and need no approver.
HARMLESS: frozenset[BlastRadius] = frozenset({BlastRadius.NONE})

#: Execution states that mean this Action has already had its turn. Evaluating
#: one again is a caller bug, and answering ALLOW would let a retry re-run a
#: remediation that already succeeded.
SPENT: frozenset[ExecutionState] = frozenset(
    {
        ExecutionState.EXECUTING,
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.ROLLED_BACK,
    }
)


@dataclass(frozen=True)
class Ruling:
    """One decision, and the rule that produced it."""

    decision: Decision
    rule: str
    because: str

    @property
    def allowed(self) -> bool:
        """True only for ALLOW.

        Named rather than left to callers comparing enum members, because
        `!= DENY` is the natural thing to write and it treats
        REQUIRE_APPROVAL as permission.
        """
        return self.decision is Decision.ALLOW

    def as_dict(self) -> dict[str, str]:
        return {"decision": self.decision.value, "rule": self.rule, "because": self.because}


def evaluate(action: Action, *, environment: Environment | None = None) -> Ruling:
    """What should happen to this Action. Ordered rules, first match wins.

    `environment` is injectable so a test can ask what production would say
    without being production. It falls back to configuration, which is the only
    module that reads the environment.
    """
    where = environment if environment is not None else get_settings().env

    if action.execution_state in SPENT:
        return Ruling(
            decision=Decision.DENY,
            rule="already-executed",
            because=(
                f"execution_state is {action.execution_state.value}: this Action has "
                "already had its turn. Re-evaluating one is a caller bug, and allowing "
                "it would let a retry re-run a remediation that already ran."
            ),
        )

    if where is Environment.PRODUCTION and action.blast_radius in IRREVERSIBLE_IN_PRODUCTION:
        return Ruling(
            decision=Decision.DENY,
            rule="too-wide-for-production",
            because=(
                f"blast radius {action.blast_radius.value} in production. Break-glass "
                "lives in core/cerberus/policy/revocation.py and is not implemented, so "
                "this is a hard deny rather than an approval nobody could grant."
            ),
        )

    if action.dry_run:
        return Ruling(
            decision=Decision.ALLOW,
            rule="dry-run",
            because=(
                "dry_run is set, so nothing changes. This assumes the connector "
                "actually implements one - a connector that ignores the flag makes "
                "this rule a lie, which is why the read/write split is the real "
                "boundary and this is only the decision."
            ),
        )

    if action.blast_radius in HARMLESS:
        return Ruling(
            decision=Decision.ALLOW,
            rule="no-blast-radius",
            because=f"blast radius {action.blast_radius.value}: nothing outside it can break.",
        )

    return Ruling(
        decision=Decision.REQUIRE_APPROVAL,
        rule="default-requires-a-human",
        because=(
            f"a {action.blast_radius.value} change in {where.value} matched no allow "
            "rule. The default is an approver rather than permission, so an operation "
            "nobody classified does not become allowed by having been added late."
        ),
    )
