"""Translate Pantheon's internal events into standard AG-UI events.

Internal events stay internal. `core/contracts/events.py` remains the bus
envelope; AG-UI is the *wire* format, and the translation happens here at the
edge. Conflating the two would make every internal change a protocol change.

THE SHARED STATE OBJECT IS THE INVESTIGATION
--------------------------------------------
AG-UI's state events carry one thing: the `Investigation`. A `StateSnapshot` at
`RunStarted`, `StateDelta` (RFC 6902 JSON Patch) for every change thereafter.

Naming it matters. "State" left undefined is how a second, competing state
object gets invented six months from now. It also makes replay trivial: the
snapshot plus the ordered patches reconstructs any run exactly, which is what
lets an operator scrub back through an incident.

EVERY PATCH IS AN `add` TO A LIST, AND THAT IS DELIBERATE
-----------------------------------------------------------
`findings/-`, `hypotheses/-`, `audit/-`. RFC 6902's `-` means "append", so a
client applying the patches in order reconstructs the same list the server has,
without either side agreeing on an index.

A `replace` at an index would break the moment two agents finished out of order,
and it would break silently: the patch applies cleanly and lands on the wrong
element. Append is the only operation whose meaning does not depend on what the
client already has.

MAPPING
-------
Domain event                    AG-UI event
----------------------------    --------------------------------------------
Investigation created           StateSnapshot(Investigation)
Investigation started           RunStarted
Investigation completed         RunFinished
Agent dispatched / finished     StepStarted / StepFinished (stepName=codename)
Finding produced                StateDelta   (findings are run state)
Hypothesis proposed             StateDelta
Verdict ready                   StateDelta
Lease expired                   StateDelta (as a Finding) + an A2UI re-approval
                                surface when the grant merely expired
Approval required               A2UI surface, via a2ui_channel
Credential access requested     A2UI surface, via a2ui_channel
Break-glass invoked             Custom("pantheon.break_glass") + StateDelta

Only one domain concept uses `Custom`. The test for an exception is not "is it
ours?" but **"must the UI act the moment it arrives, and is that action not
itself an A2UI prompt?"** Break-glass alone passes: it revokes every live lease
across every run, so an open dashboard must react immediately rather than
render a new audit row. The Custom event is the *signal*; the AuditEntry patch
is the *record*.

A REVOKED LEASE IS NOT RE-APPROVABLE
--------------------------------------
`LeaseExpiredEvent.reason` distinguishes them, and the difference is the whole
value of carrying it. An expired grant is a "grant this again?" prompt. A
revoked one is a decision somebody just made, and re-prompting for it would put
the revocation back in front of the person who performed it as a question.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    EventType,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
)
from ag_ui.core import StepFinishedEvent as AguiStepFinished
from ag_ui.core import StepStartedEvent as AguiStepStarted

from api.agui import a2ui_channel
from core.contracts.events import (
    AccessRequestedEvent,
    ApprovalRequestedEvent,
    BreakGlassEvent,
    Event,
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
from core.contracts.investigation import Investigation
from core.ui import access_surface, approval_surface, renewal_surface

#: The only Custom event Pantheon defines. See the reasoning above.
CUSTOM_EVENTS = ("pantheon.break_glass",)

#: Internal event discriminators this translator claims to map, keyed to the
#: AG-UI event family each becomes.
#:
#: This exists so the claim is checkable. Phase 0 documented a mapping in prose
#: for events the bus could not emit - `lease_expired` and `break_glass` did not
#: exist in core.contracts.events at all. A guard now asserts every name here
#: has a corresponding member of the Event union, so the table cannot describe
#: something imaginary again.
DOMAIN_EVENT_MAPPING: dict[str, str] = {
    "trigger_received": "StateSnapshot - the Investigation appears before it runs",
    "investigation_started": "RunStarted + StateSnapshot",
    "investigation_completed": "RunFinished",
    "step_started": "StepStarted",
    "step_finished": "StepFinished",
    "finding_produced": "StateDelta",
    "hypothesis_proposed": "StateDelta",
    "verdict_ready": "StateDelta",
    "approval_requested": "A2UI surface",
    "access_requested": "A2UI surface",
    "lease_expired": "StateDelta + A2UI surface when the grant merely expired",
    "break_glass": "Custom(pantheon.break_glass) + StateDelta",
}


def translate(event: Event, *, investigation: Investigation | None = None) -> list[BaseEvent]:
    """The AG-UI events one internal event becomes. Possibly several, never none.

    `investigation` is only read for the snapshot at the start of a run. Every
    other translation is a patch built from the event itself, so a caller that
    cannot supply the current Investigation still gets a correct stream - which
    matters because the bus does not carry it and reading the store on every
    event would make the edge slower than the run.

    A list rather than a generator. Callers append these to a queue, and a
    generator that was iterated twice would deliver nothing the second time,
    silently.

    Dispatched on the TYPE, not on `event.type`. A discriminated union narrows
    under `isinstance` and does not narrow through a local holding the
    discriminator, so the string version type-checked as `Any` everywhere and
    would have accepted a field that does not exist on the event in hand.
    """
    if isinstance(event, TriggerReceivedEvent):
        # The snapshot goes out before RunStarted so a client has something to
        # render the instant the run begins. An empty screen followed by a
        # populated one reads as a stall.
        return [_snapshot(investigation)] if investigation is not None else []

    if isinstance(event, InvestigationStartedEvent):
        started: list[BaseEvent] = [
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=str(event.investigation_id),
                run_id=str(event.investigation_id),
            )
        ]
        if investigation is not None:
            started.append(_snapshot(investigation))
        return started

    if isinstance(event, InvestigationCompletedEvent):
        return [
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=str(event.investigation_id),
                run_id=str(event.investigation_id),
                result={"state": event.state, "partial": event.partial},
            )
        ]

    if isinstance(event, StepStartedEvent):
        return [AguiStepStarted(type=EventType.STEP_STARTED, step_name=event.agent)]

    if isinstance(event, StepFinishedEvent):
        return [AguiStepFinished(type=EventType.STEP_FINISHED, step_name=event.agent)]

    if isinstance(event, FindingProducedEvent):
        return [_append("/findings/-", event.finding.model_dump(mode="json"))]

    if isinstance(event, HypothesisProposedEvent):
        return [_append("/hypotheses/-", event.hypothesis.model_dump(mode="json"))]

    if isinstance(event, VerdictReadyEvent):
        # `replace`, not append: an Investigation has at most one Verdict, and
        # appending would build a list of them on the client.
        return [
            StateDeltaEvent(
                type=EventType.STATE_DELTA,
                delta=[
                    {
                        "op": "replace",
                        "path": "/verdict",
                        "value": event.verdict.model_dump(mode="json"),
                    }
                ],
            )
        ]

    if isinstance(event, ApprovalRequestedEvent):
        return [
            a2ui_channel.surface_event(
                approval_surface(event.action, investigation_id=event.investigation_id)
            )
        ]

    if isinstance(event, AccessRequestedEvent):
        return [a2ui_channel.surface_event(access_surface(event.request))]

    if isinstance(event, LeaseExpiredEvent):
        lost: list[BaseEvent] = [_append("/findings/-", _lease_finding(event))]
        if event.reason == "expired":
            lost.append(
                a2ui_channel.surface_event(
                    renewal_surface(lease_id=str(event.lease_id), agent=event.agent)
                )
            )
        return lost

    if isinstance(event, BreakGlassEvent):
        signal: list[BaseEvent] = [
            CustomEvent(
                type=EventType.CUSTOM,
                name=CUSTOM_EVENTS[0],
                value={
                    "invoked_by": event.invoked_by,
                    "reason": event.reason,
                    "leases_revoked": event.leases_revoked,
                },
            )
        ]
        # The signal AND the record. A dashboard acts on the first; the audit
        # trail is reconstructed from the second, so a client that missed the
        # Custom event still ends up with the right Investigation.
        if event.audit_entry is not None:
            signal.append(_append("/audit/-", event.audit_entry.model_dump(mode="json")))
        return signal

    raise UnmappedEvent(  # pragma: no cover - guarded by test_every_event_is_mapped
        f"{event.type!r} has no AG-UI translation. Every member of the Event union "
        "needs one, or an event reaches the edge and vanishes - which looks to a "
        "client exactly like nothing happening."
    )


class UnmappedEvent(RuntimeError):
    """An internal event with no AG-UI translation.

    Raised rather than dropped. An event that silently vanished at the edge is
    indistinguishable from a run where nothing happened, and that is the worst
    failure a live view can have.
    """


def _snapshot(investigation: Investigation) -> StateSnapshotEvent:
    return StateSnapshotEvent(
        type=EventType.STATE_SNAPSHOT,
        snapshot=investigation.model_dump(mode="json"),
    )


def _append(path: str, value: Any) -> StateDeltaEvent:
    """An RFC 6902 append. See the module docstring for why never `replace`."""
    return StateDeltaEvent(
        type=EventType.STATE_DELTA,
        delta=[{"op": "add", "path": path, "value": value}],
    )


def _lease_finding(event: LeaseExpiredEvent) -> dict[str, Any]:
    """A lease expiry, as the Finding a reader will look for.

    Built here rather than by the agent because the agent that lost the lease
    may not have run again to report it - `core/cerberus/lease.py` says an
    expiry must be surfaced rather than swallowed, and this is the surfacing
    when nothing else did it.
    """
    return {
        "agent": event.agent,
        "kind": "degraded",
        "title": f"{event.agent} lost lease {event.lease_id} ({event.reason})",
        "lease_id": str(event.lease_id),
        "reason": event.reason,
    }
