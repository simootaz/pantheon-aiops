"""What Zeus decided to ask, and what actually happened when it asked.

Lives in its own module because both `Investigation` and `Verdict` need it, and
`Investigation` already needs `Verdict` - putting the plan in either one makes a
cycle. That the cycle appeared is the useful signal: the plan is a third thing,
not a detail of either.

A `PlanStep` is the **execution record**. A `Finding` is a claim. Keeping them
apart is what lets the system distinguish "the agent looked and saw nothing"
from "the agent never ran", which a finding list alone cannot express.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from core.contracts.base import ContractModel


class StepStatus(StrEnum):
    """What happened to one dispatched agent.

    COMPLETE with no findings is a real result - the agent looked and saw
    nothing. DEGRADED means it could not look. SKIPPED means it was never
    dispatched. Collapsing any of these into "no findings" makes a clean run and
    a never-run agent the same number, which is precisely the distinction agent
    scoring depends on.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class PlanStep(ContractModel):
    """One agent consultation Zeus intends to make."""

    agent: str = Field(description="Agent codename.")
    reason: str = Field(description="Why this agent is being asked.")
    depends_on: list[str] = Field(
        default_factory=list, description="Agent codenames whose findings this step needs."
    )
    status: StepStatus = StepStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
