"""Action: a proposed or executed remediation.

Every Action carries its blast radius and its approval state, because those two
fields are what the guardrail chain reads before anything touches a real system.

Phase 3 will expand this: rollback descriptors, execution receipts and an audit
trail.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel


class BlastRadius(StrEnum):
    """How much can break if this Action is wrong."""

    NONE = "none"
    SINGLE_WORKLOAD = "single_workload"
    NAMESPACE = "namespace"
    CLUSTER = "cluster"


class ApprovalState(StrEnum):
    """Where an Action sits in the human-in-the-loop gate."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Action(ContractModel):
    """A remediation Pantheon proposes, and may later execute."""

    id: UUID
    target: str = Field(description="What it acts on, e.g. 'deployment/checkout'.")
    operation: str = Field(description="What it does, e.g. 'rollout_restart'.")
    blast_radius: BlastRadius
    approval_state: ApprovalState = ApprovalState.PENDING
    dry_run: bool = Field(default=True, description="Dry run until explicitly cleared.")
    reason: str | None = Field(default=None, description="Why this Action was proposed.")


# TODO: Phase 3 - add rollback descriptors, execution receipts and audit trail
