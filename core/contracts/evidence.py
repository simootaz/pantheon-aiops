"""Evidence: one observed datum an agent collected.

A metric window, a log cluster, a manifest diff, a Kubernetes event. Evidence is
the raw material a Finding is built from.

Phase 1 will expand this: provenance chains, retention hints and per-kind
payload models. The shape here is deliberately minimal but real, so the codegen
pipeline has something to exercise.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel


class EvidenceKind(StrEnum):
    """What sort of observation this Evidence carries."""

    METRIC_WINDOW = "metric_window"
    LOG_CLUSTER = "log_cluster"
    MANIFEST_DIFF = "manifest_diff"
    K8S_EVENT = "k8s_event"
    PIPELINE_RUN = "pipeline_run"


class EvidenceSource(ContractModel):
    """Where a piece of Evidence came from, so a human can go look themselves."""

    connector: str = Field(description="Connector that produced it, e.g. 'prometheus'.")
    query: str | None = Field(default=None, description="Query that produced it, if any.")


class Evidence(ContractModel):
    """A single observation, attributable to one connector at one moment."""

    id: UUID
    kind: EvidenceKind
    source: EvidenceSource
    observed_at: datetime
    summary: str = Field(description="One-line human-readable description.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Kind-specific body. Phase 1 replaces this with per-kind models.",
    )


# TODO: Phase 1 - add per-kind payload models and a provenance chain
