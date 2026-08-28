"""Builds the agent execution plan: which agents run, and why.

ONE STEP, AND THE REASON IS NOT MODESTY
---------------------------------------
The plan has one step because one agent detects. Nine manifests load and
validate, and every one of those agents raises `NotImplementedError` - planning
a step for a stub would produce an Investigation that fails for a reason that
has nothing to do with the incident.

So the planner asks the registry which agents are *implemented*, not which are
declared. The registry is the allowlist for what may be planned, and
`IMPLEMENTED` is the narrower set of what can actually run. Lethe has landed and
joined it; the plan widened without the planner changing, which was the point.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from core.contracts.plan import PlanStep
from core.orchestrator.classifier import Classification
from core.registry import loader

#: Agents whose `investigate` does something. Deliberately a separate set from
#: the manifest roster: a manifest declares intent, and dispatching on intent is
#: how a stub ends up in a plan and fails a run for the wrong reason.
IMPLEMENTED: dict[str, str] = {
    "anomaly": "argus",
    "log_clustering": "lethe",
    "nl_query": "hermes",
}


class NoAgentForDomain(RuntimeError):
    """Nothing implemented can serve this classification.

    A distinct exception rather than an empty plan. An empty plan and a plan
    nobody could build are different states, and a run that dispatched nothing
    should not look like a run where every agent found nothing.
    """


def build(classification: Classification) -> list[PlanStep]:
    """The steps Zeus intends to take, in order.

    One step per domain the classifier named, skipping any whose agent is still
    a stub. Skipping rather than raising, because a classification naming three
    domains of which two can run should produce those two - refusing the whole
    plan would make an unimplemented agent block the implemented ones, which is
    exactly backwards.

    Raising only when NOTHING can run. An empty plan and a plan nobody could
    build are different states, and a run that dispatched nothing must not look
    like a run where every agent found nothing.

    Each step carries *why* it is being asked, because a plan whose steps have
    no reasons cannot be reviewed - and the classifier's uncertainty is part of
    that reason when it is uncertain.
    """
    reason = classification.reason
    if not classification.certain:
        reason = f"{reason}; routing was NOT determined by the trigger"

    # Both passes before any step is built. Accumulating the skips inside the
    # loop put a different reason on each step depending on where the stub fell
    # in the order, which is a plan that reads as though the omission happened
    # partway through.
    routable = [IMPLEMENTED[d] for d in classification.domains if d in IMPLEMENTED]
    skipped = sorted(domain for domain in classification.domains if domain not in IMPLEMENTED)

    if skipped:
        # Named on every step, so a reader of the plan can see what was NOT
        # looked at. An omission recorded nowhere reads as a domain nobody
        # thought of rather than one nothing can serve yet.
        reason = f"{reason} (no implemented agent for: {', '.join(skipped)})"

    steps = [
        PlanStep(agent=loader.for_codename(codename).codename, reason=reason, depends_on=[])
        for codename in routable
    ]

    if not steps:
        raise NoAgentForDomain(
            f"no implemented agent for any of {list(classification.domains)}. "
            f"Implemented: {sorted(IMPLEMENTED)}. A manifest exists for every domain, "
            "but planning a step for a stub produces a run that fails for the wrong "
            "reason."
        )
    return steps
