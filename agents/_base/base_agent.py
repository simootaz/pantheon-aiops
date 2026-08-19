"""The one shape every Pantheon agent repeats.

A SUBCLASS PROVIDES ONE COROUTINE
---------------------------------
    class Argus(BaseAgent):
        async def investigate(self, ctx: AgentContext) -> list[Finding]: ...

Nothing else is required. Identity, capabilities, the tool allowlist and the
budget all come from `agents/<domain>/manifest.yaml`, so a subclass cannot
declare a codename that disagrees with its manifest - it never declares one.

WHAT THE RUNTIME HANDLES
------------------------
* loading and validating the manifest, through `core.registry.loader`;
* binding only the tools the manifest declares, and counting every call;
* the `max_seconds` and `max_tool_calls` budget;
* stamping `agent`, `detected_at` and a **deterministic** id onto every Finding;
* publishing `FindingProducedEvent`;
* and turning any inability into a `FindingKind.DEGRADED` Finding.

DEGRADED IS THE RUNTIME'S JOB, NOT THE AGENT'S
----------------------------------------------
An agent that cannot do its job must say so, and saying so must not depend on
ten separate authors remembering to. So `run()` catches everything - a declared
`AgentDegraded`, an unreachable connector, budget exhaustion, an outright bug -
and converts it into a DEGRADED Finding. The contract exempts DEGRADED from the
evidence requirement precisely because it reports the *absence* of data.

`FindingKind.DEGRADED` is constructed in exactly one place, here, and
`tests/unit/test_agent_runtime.py` fails the build if an agent constructs one.

RETRIES
-------
Phase 2 runs `run()` inside a Temporal activity, and Temporal retries
activities. The decisions, made now because ten agents will inherit them:

* **`investigate()` need not be idempotent.** The runtime derives each Finding's
  id from its content - investigation, agent, kind, subject, window and title -
  so the same claim carries the same id on every attempt. `detected_at` is
  excluded from that key on purpose: it is wall clock, and including it would
  make every retry a new id. A retry that legitimately observes something
  different produces a different id, and both are kept. Requiring statistical
  logic over live data to be idempotent is a promise nobody keeps; making
  identical claims *identifiable* is achievable, so that is what is done.

  **Deduplication itself is only half-built, and the half that exists is here.**
  Same-id findings within one outcome are collapsed by `_collapse_duplicates`.
  Collapsing across *attempts* needs a store to upsert into, and there is no
  persistence layer yet - so today two attempts genuinely yield two objects
  carrying one id, and nothing merges them. ROADMAP tracks that against Phase 2.

* **Step lifecycle events are never emitted from here.** `StepStartedEvent` is
  documented as *"Zeus dispatched an agent"*, which makes it the dispatcher's.
  An agent does not know its plan step, so a retried `run()` cannot re-emit one.
  `tests/unit/test_agent_runtime.py` fails the build if anything under `agents/`
  constructs a step event - the claim is a guard, not a promise.
* **A crash discards that attempt's findings.** Half a claim-set presented as
  complete is worse than an honest degradation, and the deterministic id means a
  successful retry recreates them. Where partial results genuinely matter, raise
  `AgentDegraded(..., partial=[...])` and both are returned.
* **Each attempt gets a fresh budget.** Seconds and tool calls are
  per-execution resources. The aggregate bound belongs to the retry policy.
* **Budget exhaustion is not retryable**, and says so, so Phase 2 can map it to
  a non-retryable failure instead of burning attempts against the same wall.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from core.bus import EventBus
from core.contracts.events import FindingProducedEvent
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import Trigger
from core.contracts.manifest import AgentManifest
from core.registry.loader import for_domain

#: Namespace for deterministic Finding ids. Fixed forever: changing it would
#: renumber every historical Finding and break deduplication across a deploy.
FINDING_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/findings")


class AgentStatus(StrEnum):
    """How a run ended, which is not the same as what it claimed.

    `COMPLETE` with no findings is a real, useful result: the agent looked and
    saw nothing. `DEGRADED` means it could not look. Collapsing the two would
    make "no finding because clean" and "no finding because never dispatched"
    the same number, which is exactly the distinction agent scoring needs.
    """

    COMPLETE = "complete"
    DEGRADED = "degraded"


class AgentDegraded(RuntimeError):
    """Raised by an agent that cannot complete its job.

    Carries the detail the runtime cannot infer: what the agent was looking at,
    whether a retry could succeed, and any findings worth keeping from a partial
    run. The runtime turns it into the DEGRADED Finding - agents never build one.
    """

    def __init__(
        self,
        reason: str,
        *,
        subject: str | None = None,
        retryable: bool = True,
        partial: list[Finding] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.subject = subject
        self.retryable = retryable
        self.partial = partial or []


@dataclass(slots=True)
class AgentContext:
    """Everything an agent is given for one run."""

    investigation_id: UUID
    trigger: Trigger
    window_start: datetime
    window_end: datetime
    #: Set by BaseAgent before `investigate` is called.
    tools: Any = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentOutcome:
    """What a run produced, and whether it finished.

    `findings` answers "what was claimed". `status` answers "what ran". They are
    separate because a finding list is not a record of execution, and treating
    it as one is how a never-dispatched agent becomes indistinguishable from a
    clean one.
    """

    agent: str
    status: AgentStatus
    findings: list[Finding]
    started_at: datetime
    finished_at: datetime
    tool_calls: int
    degraded_reason: str | None = None
    retryable: bool = True

    @property
    def complete(self) -> bool:
        return self.status is AgentStatus.COMPLETE


class BaseAgent(ABC):
    """Lifecycle, budget, tool allowlist and degradation, once, for every agent."""

    #: Folder under `agents/`. Set by each subclass; the manifest supplies the rest.
    domain: str

    def __init__(self, bus: EventBus | None = None) -> None:
        if not getattr(self, "domain", ""):
            raise TypeError(f"{type(self).__name__} must set `domain`")
        self.manifest: AgentManifest = for_domain(self.domain)
        self.bus = bus

    @property
    def codename(self) -> str:
        return self.manifest.codename

    # -- the one thing a subclass writes ----------------------------------

    @abstractmethod
    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Do the work and return substantive Findings.

        Return `[]` when the agent looked and found nothing - that is a result,
        not a failure. Raise `AgentDegraded` when it could not look.

        Never construct a `FindingKind.DEGRADED` Finding here. The runtime owns
        that, so every agent reports inability the same way.
        """

    # -- what the runtime does around it ----------------------------------

    async def run(self, ctx: AgentContext) -> AgentOutcome:
        """Invoke `investigate` inside the budget, and never raise.

        Every exit path yields an outcome. An agent that throws produces a
        DEGRADED Finding rather than an exception the caller has to remember to
        catch, because a partial investigation must be *visibly* partial.
        """
        from agents._base.tool_binding import BoundTools, ToolBudgetExceeded

        started = datetime.now(UTC)
        tools = BoundTools(
            declared=frozenset(self.manifest.tools),
            max_calls=self.manifest.budget.max_tool_calls,
        )
        self.bind_tools(tools)
        ctx.tools = tools

        findings: list[Finding] = []
        status = AgentStatus.COMPLETE
        reason: str | None = None
        retryable = True

        try:
            async with asyncio.timeout(self.manifest.budget.max_seconds):
                findings = await self.investigate(ctx)
        except AgentDegraded as degraded:
            status = AgentStatus.DEGRADED
            reason = degraded.reason
            retryable = degraded.retryable
            findings = list(degraded.partial)
            findings.append(self._degraded_finding(ctx, degraded.reason, degraded.subject))
        except TimeoutError:
            status = AgentStatus.DEGRADED
            reason = f"exceeded its {self.manifest.budget.max_seconds}s budget"
            retryable = False
            findings = [self._degraded_finding(ctx, reason, None)]
        except ToolBudgetExceeded as exhausted:
            status = AgentStatus.DEGRADED
            reason = str(exhausted)
            retryable = False
            findings = [self._degraded_finding(ctx, reason, None)]
        except Exception as error:
            status = AgentStatus.DEGRADED
            reason = f"{type(error).__name__}: {error}"
            findings = [self._degraded_finding(ctx, reason, None)]

        # Stamping is inside the guard too. It validates what the agent returned -
        # rejecting a Finding attributed to another agent, for one - so it can
        # fail, and a failure here escaping would break the one promise run()
        # makes. This is not hypothetical: it escaped until a test caught it.
        try:
            stamped = [self._stamp(ctx, finding) for finding in findings]
        except Exception as error:
            status = AgentStatus.DEGRADED
            reason = f"returned an unusable Finding: {error}"
            retryable = False
            stamped = [self._stamp(ctx, self._degraded_finding(ctx, reason, None))]

        stamped = self._collapse_duplicates(stamped)
        await self._publish(ctx, stamped)

        return AgentOutcome(
            agent=self.codename,
            status=status,
            findings=stamped,
            started_at=started,
            finished_at=datetime.now(UTC),
            tool_calls=tools.calls_made,
            degraded_reason=reason,
            retryable=retryable,
        )

    def bind_tools(self, tools: Any) -> None:  # noqa: B027 - optional by design
        """Attach connector implementations. Overridden where an agent has them.

        Deliberately concrete-and-empty rather than abstract. An agent with no
        live connector must still construct and then degrade honestly on first
        tool use; making this abstract would turn a missing connector into a
        class that cannot be instantiated, which is a worse failure and a less
        informative one.
        """

    # -- identity and degradation, in one place ---------------------------

    def _degraded_finding(self, ctx: AgentContext, reason: str, subject: str | None) -> Finding:
        """The only place a DEGRADED Finding is constructed."""
        return Finding(
            id=UUID(int=0),  # replaced by _stamp; content is what identifies it
            agent=self.codename,
            kind=FindingKind.DEGRADED,
            title=f"{self.codename} could not complete: {reason}"[:200],
            severity=Severity.MEDIUM,
            confidence=1.0,
            detected_at=datetime.now(UTC),
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            rationale=(
                f"Reported by the {self.codename} runtime rather than by the agent, so "
                "that a partial investigation stays visibly partial."
            ),
            tags=["degraded", f"subject:{subject}" if subject else "subject:unknown"],
        )

    def _stamp(self, ctx: AgentContext, finding: Finding) -> Finding:
        """Set the agent and a deterministic id, and reject impersonation."""
        if finding.agent and finding.agent != self.codename:
            raise ValueError(
                f"{self.codename} returned a Finding attributed to {finding.agent!r}. "
                "An agent may only speak for itself."
            )
        return finding.model_copy(
            update={"agent": self.codename, "id": self.finding_id(ctx, finding)}
        )

    def finding_id(self, ctx: AgentContext, finding: Finding) -> UUID:
        """A content-derived id, stable across retries of the same claim.

        `detected_at` is deliberately not part of the key. It is wall clock, so
        including it would give every retry a fresh id and defeat the whole
        mechanism.
        """
        subject = finding.subject.model_dump_json() if finding.subject else ""
        key = "|".join(
            (
                str(ctx.investigation_id),
                self.codename,
                finding.kind.value,
                subject,
                ctx.window_start.isoformat(),
                ctx.window_end.isoformat(),
                finding.title,
            )
        )
        return uuid5(FINDING_NAMESPACE, key)

    @staticmethod
    def _collapse_duplicates(findings: list[Finding]) -> list[Finding]:
        """Two findings with the same id are the same claim, by construction.

        The id is derived from investigation, agent, kind, subject, window and
        title, so a collision means the agent said the same thing twice in one
        run. Keeping both would double-count it in every downstream consumer.

        This is the half of deduplication that can be enforced here. The other
        half - two *attempts* of a retried activity each producing that claim -
        is a persistence upsert, and there is no persistence yet. ROADMAP tracks
        it against Phase 2 rather than leaving "retries cannot duplicate" to
        stand as though it were already true.
        """
        seen: dict[UUID, Finding] = {}
        for finding in findings:
            seen.setdefault(finding.id, finding)
        return list(seen.values())

    async def _publish(self, ctx: AgentContext, findings: list[Finding]) -> None:
        if self.bus is None:
            return
        for finding in findings:
            await self.bus.publish(
                FindingProducedEvent(investigation_id=ctx.investigation_id, finding=finding),
                investigation_id=ctx.investigation_id,
            )
