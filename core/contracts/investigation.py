"""Investigation: the root aggregate.

Ties a trigger to the plan Zeus built, the Findings the agents produced and the
Verdict that came out the other end.

Phase 2 will expand this: the execution plan, per-agent budget accounting and
timing breakdowns.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel
from core.contracts.credentials import AuditEntry
from core.contracts.finding import Finding
from core.contracts.llm import ResolutionRecord
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


class Trigger(ContractModel):
    """The inbound event that started everything."""

    kind: TriggerKind
    received_at: datetime
    source: str = Field(description="Who sent it, e.g. 'alertmanager'.")
    payload: dict[str, Any] = Field(default_factory=dict)


class Investigation(ContractModel):
    """One end-to-end run, from trigger to Verdict."""

    id: UUID
    state: InvestigationState
    trigger: Trigger
    created_at: datetime
    completed_at: datetime | None = None
    findings: list[Finding] = Field(default_factory=list)
    verdict: Verdict | None = Field(
        default=None, description="Absent until the run reaches a conclusion."
    )
    resolutions: list[ResolutionRecord] = Field(
        default_factory=list,
        description="Every Delphi model resolution made during this run, in order.",
    )
    audit: list[AuditEntry] = Field(
        default_factory=list,
        description=(
            "Cerberus credential audit for this run. Safe to expose: every credential "
            "here is a CredentialRef, never a value."
        ),
    )


# TODO: Phase 2 - add the execution plan, budget accounting and timing breakdown
