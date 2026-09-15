"""Recall: prior investigations of the same alert on the same thing.

THE FIRST QUERY IS EXACT, NOT SIMILAR
---------------------------------------
ADR 0008 deferred the vector store until "Mnemosyne's manifest declares a
memory tool, which fixes the query shape". This is that tool, and the shape it
fixes needs no embedding: *the same alert, on the same subject, in this
tenant*. That is a keyed lookup, and it answers the question a responder
actually asks first - "has this happened before, and what did we conclude" -
without any notion of similarity that would have to be tuned.

"Same" is read off the trigger's own labels. Alertmanager's `alertname` is the
alert; whichever of `pod`, `service`, `node`, `instance` and `namespace` the
CURRENT alert carries is the subject, and a prior matches when it carries the
same values for the same keys. A prior missing one of those keys does not match
- a pod-level alert and a service-level alert with the same name are different
questions, and folding them together would report a service's history against
one pod.

WHAT IT SCANS
---------------
The most recent `SCAN_LIMIT` investigations in the tenant, filtered in Python.
The store answers `recent(limit)` and nothing else, which is honest about what
exists rather than an index nobody built. ADR 0008 names investigation volume
as the trigger for a query layer; when `recent` stops being enough for the
API's own listing, it stops being enough here at the same moment, and the two
decisions should be made together.

HISTORY IS CONTEXT, NOT EVIDENCE
----------------------------------
What a prior verdict concluded says nothing about what is happening now. The
same alert on the same pod that was a memory leak last Tuesday may be a bad
deploy today, and a ranker that let last Tuesday's verdict raise confidence in
this Tuesday's would entrench the first mistake anybody made. So a recalled
prior is reported for the person and is excluded from ranking - see
`hypotheses.rank`.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core.contracts.investigation import Investigation, Trigger, TriggerKind
from core.orchestrator.hypotheses import leading
from core.store.investigations import InvestigationStore

#: How many recent investigations are read before filtering. Beyond this the
#: store needs a query, not a bigger scan - ADR 0008, trigger 3.
SCAN_LIMIT = 200

#: The label keys that identify what an alert is about. Whichever of these the
#: current alert carries must match exactly on a prior.
SUBJECT_KEYS: tuple[str, ...] = ("pod", "service", "node", "instance", "namespace")

#: The name of the tool as a manifest declares it. Provided by the runtime
#: rather than a connector adapter, because it closes over the store.
TOOL_NAME = "memory.recall"


@dataclass(frozen=True)
class Prior:
    """One earlier investigation of the same alert on the same subject."""

    investigation_id: UUID
    created_at: Any
    state: str
    category: str | None
    confidence: float | None
    partial: bool


def alert_key(trigger: Trigger) -> dict[str, str] | None:
    """What makes an alert *this* alert: its name and its subject labels.

    `None` for anything that is not an alert, or an alert with no name - there
    is nothing to match a prior against, and matching on nothing would make
    every prior a match.
    """
    if trigger.kind is not TriggerKind.ALERT:
        return None
    labels = _labels(trigger)
    name = labels.get("alertname")
    if not isinstance(name, str) or not name:
        return None
    key = {"alertname": name}
    for subject in SUBJECT_KEYS:
        value = labels.get(subject)
        if isinstance(value, str) and value:
            key[subject] = value
    return key


def matches(current: Trigger, prior: Trigger) -> bool:
    """Whether `prior` is the same alert on the same subject as `current`.

    Every key the current alert carries must be present on the prior with the
    same value. Keys the prior carries and the current does not are ignored:
    the question is asked from the current alert's side.
    """
    wanted = alert_key(current)
    if wanted is None:
        return False
    have = _labels(prior) if prior.kind is TriggerKind.ALERT else {}
    return all(have.get(k) == v for k, v in wanted.items())


def priors_of(current: Investigation, candidates: list[Investigation]) -> list[Prior]:
    """The priors among `candidates`, newest first, never including `current`."""
    found = [
        _prior(candidate)
        for candidate in candidates
        if candidate.id != current.id and matches(current.trigger, candidate.trigger)
    ]
    found.sort(key=lambda prior: prior.created_at, reverse=True)
    return found


def recall_tool(
    store: InvestigationStore, *, tenant: str, current_id: UUID
) -> Callable[..., Awaitable[list[dict[str, Any]]]]:
    """`memory.recall`, closed over the store the runtime holds.

    Returns plain dicts rather than `Prior` objects because it crosses the
    tool boundary, and every other tool answers in JSON-shaped data. The
    tenant is fixed here, by the runtime, from the investigation being run -
    an agent cannot ask for another tenant's history because the tool has no
    parameter for it.
    """

    async def recall(**kwargs: Any) -> list[dict[str, Any]]:
        current = await store.get(current_id)
        if current is None:
            return []
        candidates = await store.recent(SCAN_LIMIT, tenant=tenant)
        return [
            {
                "investigation_id": str(prior.investigation_id),
                "created_at": prior.created_at.isoformat(),
                "state": prior.state,
                "category": prior.category,
                "confidence": prior.confidence,
                "partial": prior.partial,
            }
            for prior in priors_of(current, candidates)
        ]

    return recall


def _prior(investigation: Investigation) -> Prior:
    verdict = investigation.verdict
    front = leading(verdict.hypotheses) if verdict is not None else None
    partial = any(f.kind.value == "degraded" for f in investigation.findings)
    return Prior(
        investigation_id=investigation.id,
        created_at=investigation.created_at,
        state=investigation.state.value,
        category=front.category.value if front is not None else None,
        confidence=front.confidence if front is not None else None,
        partial=partial,
    )


def _labels(trigger: Trigger) -> dict[str, Any]:
    payload = trigger.payload
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts and isinstance(alerts[0], dict):
        labels = alerts[0].get("labels")
        if isinstance(labels, dict):
            return dict(labels)
    labels = payload.get("labels")
    return dict(labels) if isinstance(labels, dict) else {}


__all__ = [
    "SCAN_LIMIT",
    "SUBJECT_KEYS",
    "TOOL_NAME",
    "Prior",
    "alert_key",
    "matches",
    "priors_of",
    "recall_tool",
]
