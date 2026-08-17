"""Event envelopes published on the internal bus.

These are **internal**. AG-UI is the wire format, and `api/agui/translator.py`
maps these onto it at the edge (ADR 0006). Conflating the two would make every
internal change a protocol change.

The union is a discriminated union on a plain string `Literal`, not an enum
member, because `const` in JSON Schema is what every downstream generator reads
consistently.

WHAT THE ADRS PROMISED AND PHASE 0 DID NOT DELIVER
--------------------------------------------------
ADR 0005 requires a lease expiry to surface rather than be swallowed, and ADR
0006 names `pantheon.break_glass` as the single AG-UI `Custom` event. Neither
existed here, so the translator documented a mapping the bus could not produce -
a promise in prose that the code did not keep. `LeaseExpiredEvent` and
`BreakGlassEvent` close that, and
`tests/unit/test_contracts.py::test_translator_maps_only_events_that_exist`
stops it reopening.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from core.contracts.action import Action
from core.contracts.base import ContractModel
from core.contracts.credentials import AccessRequest, AuditEntry
from core.contracts.finding import Finding
from core.contracts.investigation import Trigger
from core.contracts.root_cause import RootCauseHypothesis
from core.contracts.verdict import Verdict


class TriggerReceivedEvent(ContractModel):
    """An inbound trigger was accepted and an Investigation created for it.

    Distinct from `investigation_started`, which marks the run leaving PENDING.
    A webhook can be accepted seconds before anything plans it, and collapsing
    the two would lose the gap where a backlog becomes visible.
    """

    type: Literal["trigger_received"] = "trigger_received"
    investigation_id: UUID
    trigger: Trigger


class InvestigationStartedEvent(ContractModel):
    """An Investigation moved out of PENDING."""

    type: Literal["investigation_started"] = "investigation_started"
    investigation_id: UUID


class InvestigationCompletedEvent(ContractModel):
    """A run reached a terminal state, successfully or not."""

    type: Literal["investigation_completed"] = "investigation_completed"
    investigation_id: UUID
    state: str = Field(description="The terminal InvestigationState value.")
    partial: bool = Field(default=False, description="True when any agent reported DEGRADED.")


class StepStartedEvent(ContractModel):
    """Zeus dispatched an agent."""

    type: Literal["step_started"] = "step_started"
    investigation_id: UUID
    agent: str


class StepFinishedEvent(ContractModel):
    """An agent returned, with or without findings."""

    type: Literal["step_finished"] = "step_finished"
    investigation_id: UUID
    agent: str
    finding_count: int = Field(default=0, ge=0)


class FindingProducedEvent(ContractModel):
    """An agent returned a Finding."""

    type: Literal["finding_produced"] = "finding_produced"
    investigation_id: UUID
    finding: Finding


class HypothesisProposedEvent(ContractModel):
    """A candidate explanation entered the running."""

    type: Literal["hypothesis_proposed"] = "hypothesis_proposed"
    investigation_id: UUID
    hypothesis: RootCauseHypothesis


class VerdictReadyEvent(ContractModel):
    """The aggregator reached a conclusion."""

    type: Literal["verdict_ready"] = "verdict_ready"
    investigation_id: UUID
    verdict: Verdict


class ApprovalRequestedEvent(ContractModel):
    """An Action needs a human before it can execute."""

    type: Literal["approval_requested"] = "approval_requested"
    investigation_id: UUID
    action: Action


class AccessRequestedEvent(ContractModel):
    """An agent asked Cerberus for a capability it has no standing grant for."""

    type: Literal["access_requested"] = "access_requested"
    investigation_id: UUID
    request: AccessRequest


class LeaseExpiredEvent(ContractModel):
    """A lease could not be renewed, so the work behind it stopped.

    ADR 0005: this must surface as a Finding and never be swallowed. `reason`
    distinguishes the two cases, because they call for opposite responses -
    an expired grant warrants offering re-approval, a revoked one must not,
    since re-prompting would undo a deliberate revocation mid-incident.
    """

    type: Literal["lease_expired"] = "lease_expired"
    investigation_id: UUID
    lease_id: UUID
    agent: str
    reason: Literal["expired", "revoked"] = "expired"


class BreakGlassEvent(ContractModel):
    """Every grant revoked and every live lease invalidated, immediately.

    The one domain concept that becomes an AG-UI `Custom` event rather than a
    state patch: it affects every run at once, so an open dashboard must react
    on arrival rather than render a new audit row (ADR 0006).
    """

    type: Literal["break_glass"] = "break_glass"
    invoked_by: str
    reason: str
    leases_revoked: int = Field(default=0, ge=0)
    audit_entry: AuditEntry | None = None


Event = Annotated[
    TriggerReceivedEvent
    | InvestigationStartedEvent
    | InvestigationCompletedEvent
    | StepStartedEvent
    | StepFinishedEvent
    | FindingProducedEvent
    | HypothesisProposedEvent
    | VerdictReadyEvent
    | ApprovalRequestedEvent
    | AccessRequestedEvent
    | LeaseExpiredEvent
    | BreakGlassEvent,
    Field(discriminator="type"),
]
"""Discriminated union of everything that can appear on the bus."""


class EventEnvelope(ContractModel):
    """Transport wrapper carrying one event plus its correlation metadata."""

    id: UUID
    emitted_at: datetime
    event: Event
    sequence: int = Field(
        default=0,
        ge=0,
        description="Monotonic within an investigation. Replay depends on order, so it "
        "is carried rather than inferred from arrival.",
    )


# TODO: Phase 3 - add delivery guarantees and replay cursors
