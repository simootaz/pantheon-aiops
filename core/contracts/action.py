"""Action: a proposed or executed remediation.

Every Action carries its blast radius and approval state, because those two
fields are what the guardrail chain reads before anything touches a real system.

An Action also carries how to undo it. A remediation without a stated rollback
is a remediation nobody should approve at three in the morning, so `rollback` is
part of the proposal rather than something worked out afterwards.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from core.contracts.base import ContractModel
from core.contracts.evidence import ResourceRef


class BlastRadius(StrEnum):
    """How much can break if this Action is wrong."""

    NONE = "none"
    SINGLE_WORKLOAD = "single_workload"
    NAMESPACE = "namespace"
    CLUSTER = "cluster"
    MULTI_CLUSTER = "multi_cluster"


class ApprovalState(StrEnum):
    """Where an Action sits in the human-in-the-loop gate."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionState(StrEnum):
    """What actually happened, as distinct from what was permitted."""

    PROPOSED = "proposed"
    DRY_RUN = "dry_run"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class ActionReceipt(ContractModel):
    """What happened when an Action ran. Written once, never amended."""

    at: datetime
    state: ExecutionState
    connector: str = Field(description="Which connector executed it.")
    detail: str = Field(default="", description="Human-readable outcome. Never a credential.")
    lease_id: UUID | None = Field(default=None, description="The lease it was executed under.")


class Action(ContractModel):
    """A remediation Pantheon proposes, and may later execute."""

    id: UUID
    target: ResourceRef
    operation: str = Field(description="What it does, e.g. 'rollout_restart', 'scale'.")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Operation arguments, e.g. {'replicas': 4}."
    )

    blast_radius: BlastRadius
    approval_state: ApprovalState = ApprovalState.PENDING
    execution_state: ExecutionState = ExecutionState.PROPOSED
    dry_run: bool = Field(default=True, description="Dry run until explicitly cleared.")

    reason: str = Field(description="Why this Action was proposed, in terms of the Verdict.")
    rollback: str | None = Field(
        default=None,
        description="How to undo it. Required for anything wider than a single workload.",
    )
    proposed_by: str = Field(description="Agent codename, or 'zeus'.")
    proposed_at: datetime
    receipts: list[ActionReceipt] = Field(
        default_factory=list, description="Append-only execution history."
    )

    @model_validator(mode="after")
    def _wide_actions_state_their_rollback(self) -> Action:
        """Anything beyond one workload must say how to undo it.

        The moment an operator is deciding is the worst moment to be working
        out whether it can be reversed.
        """
        wide = {BlastRadius.NAMESPACE, BlastRadius.CLUSTER, BlastRadius.MULTI_CLUSTER}
        if self.blast_radius in wide and not self.rollback:
            raise ValueError(
                f"Action {self.id} has blast radius {self.blast_radius.value} but states no "
                "rollback; wide actions must be reversible before they are approvable"
            )
        return self

    @model_validator(mode="after")
    def _executed_actions_are_not_dry_runs(self) -> Action:
        """A succeeded action cannot still claim to be a dry run."""
        if self.execution_state is ExecutionState.SUCCEEDED and self.dry_run:
            raise ValueError(
                f"Action {self.id} reports SUCCEEDED while dry_run is true; "
                "one of the two is wrong and both are load-bearing"
            )
        return self


# TODO: Phase 3 - link receipts to the guardrail decision that permitted them
