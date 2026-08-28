"""Investigation: the root aggregate, and the shared state object.

Ties a trigger to the plan Zeus built, the Findings agents produced, the Verdict
that came out, and the record of everything the run touched.

This is also **the** AG-UI state object: `StateSnapshot` at `RunStarted`, then
RFC 6902 `StateDelta` for every change (ADR 0006). Snapshot plus ordered patches
reconstructs any run exactly, which is what makes replay a property of the
design rather than a feature to build later.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from core.contracts.base import ContractModel
from core.contracts.credentials import AuditEntry
from core.contracts.finding import Finding
from core.contracts.llm import ResolutionRecord
from core.contracts.plan import PlanStep
from core.contracts.root_cause import RootCauseHypothesis
from core.contracts.verdict import Verdict


class InvestigationState(StrEnum):
    """Lifecycle of an Investigation."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TriggerKind(StrEnum):
    """What set an Investigation off."""

    ALERT = "alert"
    WEBHOOK = "webhook"
    SCHEDULE = "schedule"
    HUMAN_QUESTION = "human_question"
    SIMULATION = "simulation"


class Trigger(ContractModel):
    """The inbound event that started everything."""

    kind: TriggerKind
    received_at: datetime
    source: str = Field(description="Who sent it, e.g. 'alertmanager'.")
    title: str = Field(default="", description="One line, as the source described it.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Verbatim, unparsed.")


class AgentAccounting(ContractModel):
    """What one agent's step consumed, beside what it was allowed.

    EVERY FIGURE CARRIES ITS CEILING
    ----------------------------------
    "spent 16000 tokens" cannot answer the question anybody asks, which is
    whether that was close to the limit. 16000 of 16384 and 16000 of 200000 are
    different runs and the same number.

    Three resources because there are three ceilings on `AgentBudget`, and a
    breakdown missing one cannot explain a DEGRADED step that hit it. A run
    stopped by its token budget and one stopped by its clock look identical from
    the outside, and they are fixed differently.
    """

    agent: str = Field(description="Codename, e.g. 'argus'.")

    tokens_spent: int = Field(default=0, ge=0)
    token_ceiling: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tool_call_ceiling: int = Field(default=0, ge=0)
    seconds: float = Field(default=0.0, ge=0.0)
    second_ceiling: int = Field(default=0, ge=0)

    @property
    def hit_a_ceiling(self) -> str | None:
        """Which ceiling this step reached, if any.

        Computed rather than stored: a stored flag and the numbers beside it
        would be two records of one fact, and the day they disagree is the day
        somebody trusts the flag.
        """
        if self.token_ceiling and self.tokens_spent >= self.token_ceiling:
            return "tokens"
        if self.tool_call_ceiling and self.tool_calls >= self.tool_call_ceiling:
            return "tool_calls"
        if self.second_ceiling and self.seconds >= self.second_ceiling:
            return "seconds"
        return None


class Investigation(ContractModel):
    """One end-to-end run, from trigger to Verdict."""

    id: UUID
    state: InvestigationState
    trigger: Trigger
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    plan: list[PlanStep] = Field(default_factory=list, description="What Zeus decided to ask.")
    findings: list[Finding] = Field(default_factory=list)
    hypotheses: list[RootCauseHypothesis] = Field(
        default_factory=list, description="Working hypotheses, before the Verdict ranks them."
    )
    verdict: Verdict | None = Field(
        default=None, description="Absent until the run reaches a conclusion."
    )

    resolutions: list[ResolutionRecord] = Field(
        default_factory=list,
        description="Every Delphi model resolution made during this run, in order.",
    )
    accounting: list[AgentAccounting] = Field(
        default_factory=list,
        description=(
            "What each agent consumed against what it was allowed. One entry per "
            "dispatched step, including the steps that degraded - a run that "
            "exhausted its budget is the one anybody asks about."
        ),
    )
    audit: list[AuditEntry] = Field(
        default_factory=list,
        description=(
            "Cerberus credential audit for this run. Safe to expose: every credential "
            "here is a CredentialRef, never a value."
        ),
    )
    scenario: str | None = Field(
        default=None,
        description="Simulator scenario that produced this run, when triggered by one. "
        "Present so a run can be scored against known ground truth.",
    )

    @model_validator(mode="after")
    def _terminal_states_are_finished(self) -> Investigation:
        """A completed run has a completion time; a live one does not."""
        terminal = {
            InvestigationState.COMPLETED,
            InvestigationState.FAILED,
            InvestigationState.CANCELLED,
        }
        if self.state in terminal and self.completed_at is None:
            raise ValueError(
                f"Investigation {self.id} is {self.state.value} but has no completed_at"
            )
        if self.state not in terminal and self.completed_at is not None:
            raise ValueError(
                f"Investigation {self.id} is {self.state.value} but already has completed_at"
            )
        return self


# TODO: Phase 4 - link an Action back to the Finding that motivated it. Needs the
# write path, which does not exist yet, so the field would have no writer.
