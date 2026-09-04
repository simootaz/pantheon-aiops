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
from core.contracts.plan import PlanStep, StepStatus
from core.contracts.root_cause import RootCauseCategory, RootCauseHypothesis


class VerdictConfidence(StrEnum):
    """A band, for people who should not have to interpret a float.

    Derived from the numeric confidence rather than set independently, so the
    two cannot disagree.
    """

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class Dissent(ContractModel):
    """Evidence from this run that pointed somewhere other than the leading claim.

    WHAT DISSENT CAN HONESTLY MEAN HERE
    -------------------------------------
    No agent votes. Argus reports that a series moved; Lethe reports what
    appeared in the logs. Neither states an opinion about a root cause, so
    "the agents disagreed" cannot be read off anything they said.

    What IS observable is that the run produced more than one candidate and the
    leading one does not account for all the evidence. A reader told "memory
    leak, confidence 0.65" has no way to know that two of the five findings
    pointed at disk exhaustion - and that omission is the difference between a
    conclusion and a summary of the majority.

    So a Dissent is a competing hypothesis, named, with **who reported the
    evidence for it**. "Somebody disagreed" is not actionable; "Argus's disk
    signal pointed elsewhere" is.
    """

    category: RootCauseCategory = Field(description="What the dissenting evidence pointed at.")
    agents: list[str] = Field(
        default_factory=list,
        description="Codenames whose Findings support it. Named, because an unattributed "
        "disagreement is one nobody can follow up.",
    )
    finding_ids: list[UUID] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0, description="The competing hypothesis's own confidence."
    )


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

    dissent: list[Dissent] = Field(
        default_factory=list,
        description="Candidates the leading hypothesis does not account for. Empty when "
        "the run was unanimous OR when nothing led - see the validator below.",
    )
    contributing_findings: list[Finding] = Field(default_factory=list)
    recommended_actions: list[Action] = Field(default_factory=list)

    decided_at: datetime

    steps: list[PlanStep] = Field(
        description="What actually ran. REQUIRED, and deliberately not defaulted: a "
        "verdict formed without knowing which agents completed is a verdict that "
        "cannot tell 'nobody found anything' from 'nobody looked'."
    )

    @property
    def partial(self) -> bool:
        """True when the conclusion rests on incomplete evidence.

        Derived from the execution record rather than set by the caller. It was
        a free boolean, which meant a verdict could claim completeness while
        half its agents had degraded - and nothing would contradict it.
        """
        return any(step.status is not StepStatus.COMPLETE for step in self.steps)

    @property
    def degraded_agents(self) -> list[str]:
        """Who could not do their job, for the reader who asks why it is partial."""
        return sorted(step.agent for step in self.steps if step.status is StepStatus.DEGRADED)

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

    @model_validator(mode="after")
    def _dissent_needs_something_to_dissent_from(self) -> Verdict:
        """Dissent without a leading hypothesis is not dissent.

        `confidence` is 0.0 exactly when nothing leads - none proposed, or two
        tied. Recording dissent there would say the leading claim is contested
        when there is no leading claim, and a reader would go looking for the
        conclusion being argued with.

        The hypotheses are all still listed. Nothing is hidden; what is refused
        is calling one of several equals "the leader" and the rest "dissent".
        """
        if self.dissent and self.confidence == 0.0:
            raise ValueError(
                f"Verdict {self.id} records dissent with confidence 0.0, so nothing "
                "leads and there is nothing to dissent from. Two tied candidates are "
                "a run that reached no conclusion, not a majority with objectors."
            )
        return self


# Dissent is `Verdict.dissent`, built by `core/orchestrator/aggregator.py`.
#
# It is not a vote, because nothing votes. It is the evidence the leading
# hypothesis does not account for, attributed to the agents that reported it -
# which is the observable version of the question the TODO was asking.
