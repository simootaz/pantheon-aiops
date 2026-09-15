"""Finding: an agent's interpretation of one or more Evidence items.

A Finding is a claim with a confidence attached, always traceable back to the
Evidence that supports it. A Finding with no Evidence is inadmissible - not as a
style rule, but because the whole system's value is that a human can check the
reasoning rather than trust the output.

Findings are also how failures surface. An agent that could not complete its
work emits a Finding saying so (see `FindingKind.DEGRADED`) rather than
returning nothing - per ADR 0005, an investigation that quietly drops a check
produces a verdict that looks complete and is not.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from core.contracts.base import ContractModel
from core.contracts.evidence import Evidence, ResourceRef


class Severity(StrEnum):
    """How much a Finding should worry the on-call engineer."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingKind(StrEnum):
    """What sort of claim this is.

    DEGRADED is the important one: it is how an agent reports that it could not
    do its job - a lease expired, a connector was unreachable, a budget ran out.
    Making it a Finding rather than a silent absence is what keeps a partial
    investigation visibly partial.
    """

    OBSERVATION = "observation"
    ANOMALY = "anomaly"
    CORRELATION = "correlation"
    RISK = "risk"
    DEGRADED = "degraded"


class Finding(ContractModel):
    """One agent's supported claim about what it observed."""

    id: UUID
    agent: str = Field(description="Codename of the agent that produced it, e.g. 'argus'.")
    kind: FindingKind = FindingKind.OBSERVATION
    title: str = Field(description="One line, specific enough to act on.")
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0, description="The agent's own confidence, 0 to 1.")

    detected_at: datetime
    window_start: datetime | None = Field(
        default=None, description="Start of the period this claim is about."
    )
    window_end: datetime | None = None

    subject: ResourceRef | None = Field(default=None, description="What the claim is about.")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence supporting the claim. A Finding with none is inadmissible.",
    )
    related: list[UUID] = Field(
        default_factory=list,
        description=(
            "Other Findings this one connects. Populated on a CORRELATION; empty "
            "elsewhere, because a detector states what it saw and does not decide "
            "what else it belongs with."
        ),
    )
    rationale: str | None = Field(default=None, description="Why the Evidence supports the claim.")
    tags: list[str] = Field(default_factory=list, description="Free-form, for grouping.")

    @model_validator(mode="after")
    def _substantive_findings_cite_evidence(self) -> Finding:
        """Anything but a DEGRADED report must cite Evidence.

        DEGRADED is exempt precisely because it reports the *absence* of data -
        an agent that could not reach a connector has nothing to cite, and
        requiring it to invent something would defeat the purpose.
        """
        if self.kind is not FindingKind.DEGRADED and not self.evidence:
            raise ValueError(
                f"Finding {self.id} is {self.kind.value} but cites no evidence; "
                "only DEGRADED findings may be evidence-free"
            )
        return self


# `related` above is what core/orchestrator/correlation.py populates. It says
# these Findings are about ONE RESOURCE IN ONE WINDOW - a fact - and deliberately
# not that they share a cause, which is the judgement nothing here makes yet.
#
# TODO: Phase 5 - rank correlated groups into hypotheses. Needs something that
# can weigh "the memory anomaly caused the OOM" against the reverse, and that is
# a reasoning step scored against simulator/scenarios/*.yaml ground truth.
