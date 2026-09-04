"""Executes the plan: constructs each agent, binds its tools, runs it.

WHERE DURABLE EXECUTION WOULD GO, AND WHY IT IS NOT HERE YET
-------------------------------------------------------------
This is a loop over steps. That is the right shape for a plan of one step with
no waits, no retries and no external dependencies: a workflow engine buys
durable timers and signals, and nothing here needs one.

It is also the single place that would change. Every step goes through
`_run_step`, so moving execution into Temporal means replacing one function
rather than unpicking the orchestrator - which is what makes deferring it cheap
rather than a debt. ADR 0007 is explicit that Temporal becomes load-bearing when
Chronos arrives, because an hour-long wait that survives a deploy is not
something a loop does.

The two things that will force it, stated so the decision can be checked later:
`StepStatus.AWAITING_EXTERNAL`, and retries that must survive a worker restart.
Neither exists yet.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from agents._base.base_agent import AgentContext, AgentOutcome, AgentStatus, BaseAgent
from core.contracts.investigation import Trigger
from core.contracts.plan import PlanStep, StepStatus
from core.orchestrator.classifier import subject_of

#: Codename to the class that implements it. Not discovered by import scanning:
#: a registry that finds agents by walking the filesystem will one day find a
#: half-written one, and the failure surfaces at dispatch.
AGENTS: dict[str, type[BaseAgent]] = {}


def register(codename: str, agent: type[BaseAgent]) -> None:
    """Make an implemented agent dispatchable."""
    AGENTS[codename] = agent


class AgentNotDispatchable(RuntimeError):
    """The plan names an agent with no implementation registered."""


async def run_step(
    step: PlanStep,
    *,
    investigation_id: UUID,
    trigger: Trigger,
    window_start: datetime,
    window_end: datetime,
) -> tuple[PlanStep, AgentOutcome]:
    """Run one step and return it updated, with what the agent produced.

    The step is returned rather than mutated in place so that the caller decides
    when the Investigation changes - which keeps "what ran" and "what was
    recorded" from drifting apart when a save fails between them.
    """
    implementation = AGENTS.get(step.agent)
    if implementation is None:
        raise AgentNotDispatchable(
            f"plan names {step.agent!r} and no implementation is registered. "
            f"Registered: {sorted(AGENTS)}. A manifest is not an implementation."
        )

    agent = implementation()

    # No toolset is passed. `BaseAgent.run` builds one from the manifest and
    # calls `bind_tools`, replacing anything set here - so an orchestrator that
    # supplied its own would be handing over an object the runtime discards.
    ctx = AgentContext(
        investigation_id=investigation_id,
        trigger=trigger,
        window_start=window_start,
        window_end=window_end,
        # What the trigger is ABOUT, when it is about one thing. Empty for an
        # alert: Argus and Lethe take the window, which is already here. A pull
        # request or a CI run is a subject rather than a window, and an agent
        # pointed at one cannot find it from a time range.
        params=subject_of(trigger),
    )

    started = datetime.now(UTC)
    outcome = await agent.run(ctx)

    return (
        step.model_copy(
            update={
                "status": _status_of(outcome),
                "started_at": started,
                "finished_at": datetime.now(UTC),
            }
        ),
        outcome,
    )


def _status_of(outcome: AgentOutcome) -> StepStatus:
    """Map how the agent ended onto how the step ended.

    `COMPLETE` with no findings stays COMPLETE. Downgrading it because the list
    is empty would erase the distinction the whole contract is built around:
    the agent looked and saw nothing.

    Exhaustive rather than defaulted. `AgentStatus` has exactly two members and
    a fallback would silently absorb a third if one were added - which is how a
    new failure mode ends up reported as an old one.
    """
    if outcome.status is AgentStatus.COMPLETE:
        return StepStatus.COMPLETE
    if outcome.status is AgentStatus.DEGRADED:
        return StepStatus.DEGRADED
    raise AssertionError(f"unhandled AgentStatus {outcome.status!r}; add it here deliberately")
