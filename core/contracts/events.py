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
from enum import StrEnum
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


class DeliveryGuarantee(StrEnum):
    """What a bus implementation promises. Declared, not assumed.

    A consumer that needs "every event or tell me" cannot get it from a bus
    that offers less, and the only thing worse than a bus that loses events is
    one that loses them while something downstream believes it does not.

    So the guarantee is a property of the implementation and is READ rather
    than hoped for. `InMemoryEventBus` declares AT_MOST_ONCE, which is the
    truth: nothing is persisted, nothing is acknowledged, and a process that
    dies takes everything with it.
    """

    #: Delivered zero or one times. No durability, no acknowledgement.
    AT_MOST_ONCE = "at_most_once"
    #: Delivered at least once; a consumer must tolerate a repeat.
    AT_LEAST_ONCE = "at_least_once"
    #: Delivered exactly once. Nothing here offers this and probably nothing
    #: will - it is listed so a consumer requiring it fails loudly against a
    #: bus that does not, rather than being unable to express the requirement.
    EXACTLY_ONCE = "exactly_once"


class ReplayCursor(ContractModel):
    """Where one consumer has read up to, and what it noticed missing.

    A GAP IS A FACT, NOT A SKIP
    -----------------------------
    Sequence numbers are monotonic within an investigation, so a consumer that
    sees 5 after 3 knows it missed 4. That is what makes AT_MOST_ONCE workable:
    the loss is detectable at the consumer rather than invisible.

    `gaps` counts them. A consumer reading a run with a non-zero gap count has a
    partial picture and can say so - the same choice as `AgentDegraded`, where a
    run that could not finish reports it instead of returning a short answer
    that looks complete.

    `sequence` is None until something has been seen. Not -1 and not 0: the bus
    numbers from 0, so "seen nothing" and "seen the first event" are different
    facts and a sentinel that conflated them would drop the first event of every
    run.
    """

    investigation_id: UUID | None = Field(
        default=None, description="The run this cursor is reading. Null for unscoped events."
    )
    sequence: int | None = Field(
        default=None, ge=0, description="Last sequence seen. Null when nothing has been."
    )
    gaps: int = Field(default=0, ge=0, description="How many events are known to be missing.")

    def accepts(self, envelope: EventEnvelope) -> bool:
        """Whether this envelope is new to the cursor.

        False for anything already seen. A consumer that reprocessed a repeat
        would double-count, and on this bus a repeat is what a retry looks
        like.
        """
        return self.sequence is None or envelope.sequence > self.sequence

    def advanced(self, envelope: EventEnvelope) -> ReplayCursor:
        """The cursor after reading `envelope`. Returns a new one.

        Never rewinds. An envelope arriving out of order with a lower sequence
        leaves the cursor where it is - moving it back would replay everything
        after it, which turns one late event into a storm of duplicates.

        The gap is counted from the distance, not from a boolean. Missing one
        event and missing forty are different situations and only the count
        says which.
        """
        if not self.accepts(envelope):
            return self

        missed = 0 if self.sequence is None else envelope.sequence - self.sequence - 1
        return self.model_copy(
            update={"sequence": envelope.sequence, "gaps": self.gaps + max(missed, 0)}
        )

    @property
    def complete(self) -> bool:
        """Whether this consumer has seen everything it was sent."""
        return self.gaps == 0
