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

from core.contracts.action import (
    Action,
    ActionReceipt,
    ApprovalState,
    BlastRadius,
    ExecutionState,
)
from core.contracts.credentials import (
    AccessRequest,
    AuditEntry,
    AuditEvent,
    CredentialAction,
    CredentialRef,
    CredentialScope,
    CredentialType,
    Grant,
    Lease,
    PermissionMode,
)
from core.contracts.events import (
    AccessRequestedEvent,
    ApprovalRequestedEvent,
    BreakGlassEvent,
    EventEnvelope,
    FindingProducedEvent,
    HypothesisProposedEvent,
    InvestigationCompletedEvent,
    InvestigationStartedEvent,
    LeaseExpiredEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TriggerReceivedEvent,
    VerdictReadyEvent,
)
from core.contracts.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceSource,
    K8sEventPayload,
    LogClusterPayload,
    ManifestDiffPayload,
    MetricSample,
    MetricWindowPayload,
    PipelineRunPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import (
    Investigation,
    InvestigationState,
    PlanStep,
    Trigger,
    TriggerKind,
)
from core.contracts.llm import (
    AuthMode,
    Capability,
    Dialect,
    ModelDescriptor,
    ModelRequirements,
    ProviderConfig,
    ResolutionRecord,
    ResolutionStep,
    Tier,
)
from core.contracts.manifest import AgentBudget, AgentCapability, AgentManifest
from core.contracts.root_cause import (
    HypothesisStatus,
    RootCauseCategory,
    RootCauseHypothesis,
)
from core.contracts.ui import (
    A2UIAction,
    A2UIClientCapabilities,
    A2UIComponent,
    A2UIComponentType,
    A2UISurface,
    A2UISurfaceKind,
    ArtifactKind,
    ArtifactRef,
    UIActionResponse,
)
from core.contracts.verdict import Verdict, VerdictConfidence

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
    RootCauseHypothesis,
    ProviderConfig,
    ModelDescriptor,
    ModelRequirements,
    ResolutionRecord,
    CredentialRef,
    Grant,
    AccessRequest,
    Lease,
    AuditEntry,
    A2UISurface,
    A2UIClientCapabilities,
    UIActionResponse,
)

__all__ = [
    "EXPORTED_MODELS",
    "A2UIAction",
    "A2UIClientCapabilities",
    "A2UIComponent",
    "A2UIComponentType",
    "A2UISurface",
    "A2UISurfaceKind",
    "AccessRequest",
    "AccessRequestedEvent",
    "Action",
    "ActionReceipt",
    "AgentBudget",
    "AgentCapability",
    "AgentManifest",
    "ApprovalRequestedEvent",
    "ApprovalState",
    "ArtifactKind",
    "ArtifactRef",
    "AuditEntry",
    "AuditEvent",
    "AuthMode",
    "BlastRadius",
    "BreakGlassEvent",
    "Capability",
    "CredentialAction",
    "CredentialRef",
    "CredentialScope",
    "CredentialType",
    "Dialect",
    "EventEnvelope",
    "Evidence",
    "EvidenceKind",
    "EvidenceSource",
    "ExecutionState",
    "Finding",
    "FindingKind",
    "FindingProducedEvent",
    "Grant",
    "HypothesisProposedEvent",
    "HypothesisStatus",
    "Investigation",
    "InvestigationCompletedEvent",
    "InvestigationStartedEvent",
    "InvestigationState",
    "K8sEventPayload",
    "Lease",
    "LeaseExpiredEvent",
    "LogClusterPayload",
    "ManifestDiffPayload",
    "MetricSample",
    "MetricWindowPayload",
    "ModelDescriptor",
    "ModelRequirements",
    "PermissionMode",
    "PipelineRunPayload",
    "PlanStep",
    "ProviderConfig",
    "ResolutionRecord",
    "ResolutionStep",
    "ResourceRef",
    "RootCauseCategory",
    "RootCauseHypothesis",
    "Severity",
    "StepFinishedEvent",
    "StepStartedEvent",
    "Tier",
    "Trigger",
    "TriggerKind",
    "TriggerReceivedEvent",
    "UIActionResponse",
    "Verdict",
    "VerdictConfidence",
    "VerdictReadyEvent",
]
