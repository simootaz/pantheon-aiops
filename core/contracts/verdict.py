"""Verdict: Zeus's aggregated conclusion across all agent Findings.

One Investigation produces at most one Verdict. It is what a human reads first,
so it ranks hypotheses rather than asserting one - an incident with a single
confident explanation and no alternatives considered is usually an incident
where the second explanation was the right one.

`root_cause: str | None` from Phase 0 is gone. Prose cannot be scored against
ground truth, and scoring agents is the reason the simulator exists. Hypotheses
carry a `RootCauseCategory` from a closed vocabulary that
`simulator/scenarios/*.yaml` also draws from.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from core.contracts.action import Action
from core.contracts.base import ContractModel
from core.contracts.finding import Finding
from core.contracts.root_cause import RootCauseHypothesis


class VerdictConfidence(StrEnum):
    """A band, for people who should not have to interpret a float.

    Derived from the numeric confidence rather than set independently, so the
    two cannot disagree.
    """

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Verdict(ContractModel):
    """The orchestrator's ranked conclusion for one Investigation."""

    id: UUID
    investigation_id: UUID
    summary: str = Field(description="What happened, in one paragraph, for a human.")

    hypotheses: list[RootCauseHypothesis] = Field(
        default_factory=list,
        description="Ranked most-likely first. Empty means no explanation was reached, "
        "which is a legitimate outcome and must not be dressed up as one.",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the leading hypothesis.")

    contributing_findings: list[Finding] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)

    decided_at: datetime
    partial: bool = Field(
        default=False,
        description="True when an agent reported DEGRADED, so the conclusion rests on "
        "incomplete evidence. Surfaced to the reader rather than buried.",
    )

    @property
    def leading(self) -> RootCauseHypothesis | None:
        """The top-ranked hypothesis, or None when nothing was concluded."""
        return self.hypotheses[0] if self.hypotheses else None

    @property
    def band(self) -> VerdictConfidence:
        """Confidence as a band, derived so it cannot disagree with the number."""
        if self.confidence >= 0.75:
            return VerdictConfidence.HIGH
        if self.confidence >= 0.4:
            return VerdictConfidence.MODERATE
        return VerdictConfidence.LOW

    @model_validator(mode="after")
    def _confidence_matches_the_evidence(self) -> Verdict:
        """A confident verdict needs a hypothesis to be confident about."""
        if not self.hypotheses and self.confidence > 0.0:
            raise ValueError(
                f"Verdict {self.id} states confidence {self.confidence} with no hypotheses; "
                "confidence in nothing is not a conclusion"
            )
        return self


# TODO: Phase 2 - record dissent when agents disagree about the leading hypothesis
