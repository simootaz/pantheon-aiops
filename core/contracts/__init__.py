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
from core.contracts.ui import (
    A2UIAction,
    A2UIClientCapabilities,
    A2UIComponent,
    A2UIComponentType,
    A2UISurface,
    A2UISurfaceKind,
    UIActionResponse,
)
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
    "Action",
    "AgentBudget",
    "AgentCapability",
    "AgentManifest",
    "ApprovalRequestedEvent",
    "ApprovalState",
    "AuditEntry",
    "AuditEvent",
    "AuthMode",
    "BlastRadius",
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
    "Finding",
    "FindingProducedEvent",
    "Grant",
    "Investigation",
    "InvestigationStartedEvent",
    "InvestigationState",
    "Lease",
    "ModelDescriptor",
    "ModelRequirements",
    "PermissionMode",
    "ProviderConfig",
    "ResolutionRecord",
    "ResolutionStep",
    "Severity",
    "Tier",
    "Trigger",
    "TriggerKind",
    "UIActionResponse",
    "Verdict",
    "VerdictReadyEvent",
]
