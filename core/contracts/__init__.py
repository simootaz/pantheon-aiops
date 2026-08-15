"""Source of truth for every cross-language data shape in Pantheon.

Pydantic v2 models defined here are exported to JSON Schema by
codegen/export_schemas.py, and Go structs and TypeScript types are generated
from that schema. Hand-writing a mirrored type in Go or TypeScript is forbidden.

`EXPORTED_MODELS` is what the exporter walks. A model that is not listed here is
not exported, so add new top-level models to it.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from pydantic import BaseModel

from core.contracts.action import Action, ApprovalState, BlastRadius
from core.contracts.events import (
    ApprovalRequestedEvent,
    EventEnvelope,
    FindingProducedEvent,
    InvestigationStartedEvent,
    VerdictReadyEvent,
)
from core.contracts.evidence import Evidence, EvidenceKind, EvidenceSource
from core.contracts.finding import Finding, Severity
from core.contracts.investigation import (
    Investigation,
    InvestigationState,
    Trigger,
    TriggerKind,
)
from core.contracts.manifest import AgentBudget, AgentManifest, Capability
from core.contracts.verdict import Verdict

# Top-level models the codegen pipeline exports. Nested models reachable from
# these are pulled in automatically as $defs - they do not need listing.
EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    Evidence,
    Finding,
    Action,
    Verdict,
    Investigation,
    AgentManifest,
    EventEnvelope,
)

__all__ = [
    "EXPORTED_MODELS",
    "Action",
    "AgentBudget",
    "AgentManifest",
    "ApprovalRequestedEvent",
    "ApprovalState",
    "BlastRadius",
    "Capability",
    "EventEnvelope",
    "Evidence",
    "EvidenceKind",
    "EvidenceSource",
    "Finding",
    "FindingProducedEvent",
    "Investigation",
    "InvestigationStartedEvent",
    "InvestigationState",
    "Severity",
    "Trigger",
    "TriggerKind",
    "Verdict",
    "VerdictReadyEvent",
]
