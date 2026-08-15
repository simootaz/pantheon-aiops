"""Finding: an agent's interpretation of one or more Evidence items.

A Finding is a claim with a confidence attached, always traceable back to the
Evidence that supports it.

Phase 1 will expand this: correlation ids linking Findings across agents, and
per-domain Finding subtypes.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel
from core.contracts.evidence import Evidence


class Severity(StrEnum):
    """How much a Finding should worry the on-call engineer."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(ContractModel):
    """One agent's supported claim about what it observed."""

    id: UUID
    agent: str = Field(description="Codename of the agent that produced it, e.g. 'argus'.")
    title: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0, description="Agent's own confidence, 0 to 1.")
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="Evidence supporting the claim. A Finding with none is inadmissible.",
    )
    rationale: str | None = Field(default=None, description="Why the Evidence supports the claim.")


# TODO: Phase 1 - add cross-agent correlation ids and per-domain subtypes
