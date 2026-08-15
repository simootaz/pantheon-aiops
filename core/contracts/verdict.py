"""Verdict: Zeus's aggregated conclusion across all agent Findings.

One Investigation produces at most one Verdict. The Verdict is what a human
reads first, so it names a root cause, cites the Findings that support it and
proposes what to do about it.

Phase 2 will expand this: competing hypotheses with per-hypothesis confidence,
and a dissent record when agents disagree.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from core.contracts.action import Action
from core.contracts.base import ContractModel
from core.contracts.finding import Finding


class Verdict(ContractModel):
    """The orchestrator's ranked conclusion for one Investigation."""

    id: UUID
    investigation_id: UUID
    root_cause: str | None = Field(
        default=None, description="Null when the evidence does not support a conclusion."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    contributing_findings: list[Finding] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)


# TODO: Phase 2 - add competing hypotheses and a dissent record
