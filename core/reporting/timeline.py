"""The timeline: what happened in a run, in the order it was recorded.

A RENDERING, NOT A FINDING
----------------------------
Clio's manifest declared `write_timeline` as an agent capability. It is not
one. A timeline is a pure function of the Investigation's own timestamps -
the trigger's arrival, each step's start and finish, each Finding's report,
each model consultation, each credential event, the verdict, the close - and
running an agent to produce it would put "what happened so far" in the
Findings list, which is a list of claims about the incident. This module
orders records; it claims nothing.

WHEN A FINDING HAPPENED
-------------------------
`Finding.detected_at` is when the agent reported it. `window_start` and
`window_end` are when the thing it describes was going on. The entry is placed
at the report and says what window it covers, because placing it at the window
would put an anomaly on the timeline at a moment nobody had yet noticed it - a
timeline that reads as if the system knew things before it did.

TIES KEEP RECORD ORDER
------------------------
Two records at the same instant are emitted in the order they were read off
the Investigation: trigger, lifecycle, steps, findings, consultations, audit,
verdict. A sort that was not stable would put a step's finish before its start
when both carry one timestamp, which a fast agent produces routinely.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from core.contracts.finding import FindingKind
from core.contracts.investigation import Investigation


class EntryKind(StrEnum):
    """What sort of thing an entry marks. Closed, so a renderer can switch on it."""

    TRIGGER = "trigger"
    STARTED = "started"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    FINDING = "finding"
    DEGRADED = "degraded"
    CONSULTATION = "consultation"
    CREDENTIAL = "credential"
    VERDICT = "verdict"
    COMPLETED = "completed"


@dataclass(frozen=True)
class TimelineEntry:
    """One thing that happened, when, and who did it."""

    at: datetime
    kind: EntryKind
    actor: str
    summary: str
    #: The id of the record this entry was read from, for a reader who wants
    #: the whole thing. None for lifecycle moments that have no record of
    #: their own.
    ref: str | None = None


def timeline(investigation: Investigation) -> list[TimelineEntry]:
    """Every recorded moment of the run, oldest first."""
    entries: list[TimelineEntry] = []

    trigger = investigation.trigger
    entries.append(
        TimelineEntry(
            at=trigger.received_at,
            kind=EntryKind.TRIGGER,
            actor=trigger.source,
            summary=trigger.title or f"{trigger.kind.value} received",
        )
    )
    if investigation.started_at is not None:
        entries.append(
            TimelineEntry(
                at=investigation.started_at,
                kind=EntryKind.STARTED,
                actor="zeus",
                summary="investigation started",
            )
        )

    for step in investigation.plan:
        if step.started_at is not None:
            entries.append(
                TimelineEntry(
                    at=step.started_at,
                    kind=EntryKind.STEP_STARTED,
                    actor=step.agent,
                    summary=f"{step.agent} dispatched: {step.reason}",
                )
            )
        if step.finished_at is not None:
            entries.append(
                TimelineEntry(
                    at=step.finished_at,
                    kind=EntryKind.STEP_FINISHED,
                    actor=step.agent,
                    summary=f"{step.agent} {step.status.value}",
                )
            )

    for finding in investigation.findings:
        degraded = finding.kind is FindingKind.DEGRADED
        entries.append(
            TimelineEntry(
                at=finding.detected_at,
                kind=EntryKind.DEGRADED if degraded else EntryKind.FINDING,
                actor=finding.agent,
                summary=(
                    f"{finding.agent} could not look: {finding.title}"
                    if degraded
                    else f"{finding.agent} reported {finding.kind.value}: {finding.title}"
                    + _window(finding.window_start, finding.window_end)
                ),
                ref=str(finding.id),
            )
        )

    for record in investigation.resolutions:
        entries.append(
            TimelineEntry(
                at=record.resolved_at,
                kind=EntryKind.CONSULTATION,
                actor=record.requested_by,
                summary=(
                    f"{record.requested_by} consulted "
                    f"{record.chosen.provider_id}/{record.chosen.model_id} "
                    f"({record.matched_step.value})"
                ),
                ref=str(record.id),
            )
        )

    for entry in investigation.audit:
        entries.append(
            TimelineEntry(
                at=entry.at,
                kind=EntryKind.CREDENTIAL,
                actor=entry.actor,
                summary=f"{entry.event.value}: {entry.detail}"
                if entry.detail
                else entry.event.value,
                ref=str(entry.id),
            )
        )

    verdict = investigation.verdict
    if verdict is not None:
        entries.append(
            TimelineEntry(
                at=verdict.decided_at,
                kind=EntryKind.VERDICT,
                actor="zeus",
                summary=verdict.summary,
                ref=str(verdict.id),
            )
        )
    if investigation.completed_at is not None:
        entries.append(
            TimelineEntry(
                at=investigation.completed_at,
                kind=EntryKind.COMPLETED,
                actor="zeus",
                summary=f"investigation {investigation.state.value}",
            )
        )

    # Stable: ties keep the order above.
    entries.sort(key=lambda entry: entry.at)
    return entries


def _window(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return ""
    return f" (over {start.isoformat(timespec='seconds')} to {end.isoformat(timespec='seconds')})"


__all__ = ["EntryKind", "TimelineEntry", "timeline"]
