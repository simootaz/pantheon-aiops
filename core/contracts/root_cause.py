"""RootCauseHypothesis: a claim about *why*, with the evidence for and against.

Phase 0 modelled root cause as `Verdict.root_cause: str | None` - free prose.
That is unusable for the thing it exists to support: scoring an agent against a
known answer. Comparing prose to prose means string matching, and string
matching means an agent that says "the connection pool was exhausted" scores
zero against ground truth that says "pool exhaustion".

So the category is a **closed vocabulary**, and `simulator/scenarios/*.yaml`
declares its `expected_root_cause` from that same vocabulary. A guard asserts
every scenario resolves to a real member - ground truth that cannot be parsed is
ground truth nobody checks.

A hypothesis carries its *contradicting* evidence as well as its supporting
evidence. An investigation that only records what agreed with it is not an
investigation.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel


class RootCauseCategory(StrEnum):
    """The closed vocabulary shared by agents, verdicts and scenario ground truth.

    Adding a member is a deliberate act: it widens what an agent may conclude
    and what a scenario may assert. `UNKNOWN` exists so that "we do not know" is
    a statable conclusion rather than an absent one - an investigation that
    cannot say it will invent something instead.
    """

    MEMORY_LEAK = "memory_leak"
    RESOURCE_CONTENTION = "resource_contention"
    BAD_DEPLOYMENT = "bad_deployment"
    CONFIG_ERROR = "config_error"
    DISK_EXHAUSTION = "disk_exhaustion"
    CAPACITY_SATURATION = "capacity_saturation"
    DEPENDENCY_FAILURE = "dependency_failure"
    NETWORK_PARTITION = "network_partition"
    FLAKY_TEST = "flaky_test"
    DATA_CORRUPTION = "data_corruption"
    EXTERNAL_INCIDENT = "external_incident"
    UNKNOWN = "unknown"


class HypothesisStatus(StrEnum):
    """Where a hypothesis stands once the evidence is in."""

    PROPOSED = "proposed"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class RootCauseHypothesis(ContractModel):
    """One candidate explanation, and how well it survived contact with evidence."""

    id: UUID
    category: RootCauseCategory
    statement: str = Field(
        description="One sentence a human can act on, e.g. 'checkout leaks connections "
        "under retry storms, exhausting the pool'."
    )
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    confidence: float = Field(ge=0.0, le=1.0)
    proposed_by: str = Field(description="Agent codename, or 'zeus' for an aggregated one.")

    supporting_finding_ids: list[UUID] = Field(default_factory=list)
    contradicting_finding_ids: list[UUID] = Field(
        default_factory=list,
        description="Recorded deliberately. A hypothesis with none listed has usually "
        "not been tested, rather than survived testing.",
    )

    subject: str | None = Field(
        default=None, description="What it is about, e.g. 'deployment/checkout'."
    )
    reasoning: str | None = Field(default=None, description="Why the evidence implies this.")


# TODO: Phase 4 - add per-category structured detail once something produces it.
#
# HALF OF THE ORIGINAL BLOCKER IS GONE, AND HALF IS NOT.
#
# The old reason was "no agent emits a RootCauseCategory, because nothing
# proposes a hypothesis". That stopped being true: `core/orchestrator/
# hypotheses.py` proposes them, so categories are now produced.
#
# What is still missing is the DETAIL. A structured memory-leak detail would
# carry a growth rate and the pod it was measured on; a disk-exhaustion detail
# would carry the fill rate and time-to-full. Nothing computes either. The
# ranker names a category from the fact that a threshold was crossed, and it has
# no more than that to put in a detail field.
#
# So adding one now means designing the shape of a number nobody produces, and
# the categories are what simulator/scenarios/*.yaml scores against - a guessed
# shape would be scored as though it were reasoning. Moved to Phase 4, where the
# per-category work sits with the agents that would compute it.
