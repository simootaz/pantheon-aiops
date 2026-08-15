"""Event envelopes published on the internal bus and streamed to the dashboard.

This module is the codegen pipeline's hardest case on purpose: a discriminated
union. The discriminator is a plain string Literal rather than an enum member,
because `const` in JSON Schema is what every downstream generator understands.
Using an enum here produces a schema that Go and TypeScript generators read
inconsistently.

Phase 3 will expand this: per-event delivery guarantees and replay cursors.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from core.contracts.action import Action
from core.contracts.base import ContractModel
from core.contracts.finding import Finding
from core.contracts.verdict import Verdict


class InvestigationStartedEvent(ContractModel):
    """An Investigation moved out of PENDING."""

    type: Literal["investigation_started"] = "investigation_started"
    investigation_id: UUID


class FindingProducedEvent(ContractModel):
    """An agent returned a Finding."""

    type: Literal["finding_produced"] = "finding_produced"
    investigation_id: UUID
    finding: Finding


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


Event = Annotated[
    InvestigationStartedEvent | FindingProducedEvent | VerdictReadyEvent | ApprovalRequestedEvent,
    Field(discriminator="type"),
]
"""Discriminated union of everything that can appear on the bus."""


class EventEnvelope(ContractModel):
    """Transport wrapper carrying one event plus its correlation metadata."""

    id: UUID
    emitted_at: datetime
    event: Event


# TODO: Phase 3 - add delivery guarantees and replay cursors
