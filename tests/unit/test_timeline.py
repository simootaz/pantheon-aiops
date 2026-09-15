"""The timeline: an ordering of what the run recorded, and nothing it did not.

Two things a timeline can get wrong are worth a test each. It can place a
Finding at the moment the thing happened rather than the moment it was
noticed, which reads as if the system knew things before it did. And it can
reorder two records at one instant, which puts a step's finish before its
start whenever an agent is fast. Everything else is that the entries are the
records, and the records are all there.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth.dependencies import _principals
from api.main import create_app
from core.config import get_settings
from core.contracts.evidence import Evidence, EvidenceSource, LogClusterPayload, ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.investigation import Investigation, InvestigationState, Trigger, TriggerKind
from core.contracts.plan import PlanStep, StepStatus
from core.contracts.verdict import Verdict
from core.reporting import EntryKind, timeline
from core.store.investigations import InMemoryInvestigationStore

T0 = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _finding(agent: str, title: str, *, reported: float, window: tuple[float, float]) -> Finding:
    subject = ResourceRef(kind="pod", name="checkout-7f9")
    return Finding(
        id=uuid4(),
        agent=agent,
        kind=FindingKind.ANOMALY,
        title=title,
        severity=Severity.MEDIUM,
        confidence=0.8,
        detected_at=_at(reported),
        window_start=_at(window[0]),
        window_end=_at(window[1]),
        subject=subject,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query="q"),
                observed_at=_at(reported),
                summary="s",
                subject=subject,
                payload=LogClusterPayload(template="t", occurrences=1),
            )
        ],
    )


def _run(*, tenant: str = "acme") -> Investigation:
    """A finished run with one step, one finding, one degraded step, a verdict."""
    identifier = uuid4()
    findings = [
        _finding("argus", "memory crossed its threshold", reported=12.0, window=(-300.0, 10.0)),
        _finding("lethe", "log search never ran", reported=15.0, window=(-300.0, 10.0)).model_copy(
            update={"kind": FindingKind.DEGRADED}
        ),
    ]
    return Investigation(
        id=identifier,
        state=InvestigationState.COMPLETED,
        trigger=Trigger(
            kind=TriggerKind.ALERT,
            received_at=_at(0.0),
            source="alertmanager",
            title="checkout pods restarting",
        ),
        created_at=_at(1.0),
        started_at=_at(2.0),
        completed_at=_at(20.0),
        tenant=tenant,
        plan=[
            PlanStep(
                agent="argus",
                reason="metrics",
                depends_on=[],
                status=StepStatus.COMPLETE,
                started_at=_at(3.0),
                finished_at=_at(12.0),
            ),
            PlanStep(
                agent="lethe",
                reason="logs",
                depends_on=[],
                status=StepStatus.DEGRADED,
                started_at=_at(12.0),
                finished_at=_at(15.0),
            ),
        ],
        findings=findings,
        verdict=Verdict(
            id=uuid4(),
            investigation_id=identifier,
            summary="argus detected 1 threshold crossing",
            hypotheses=[],
            confidence=0.0,
            decided_at=_at(18.0),
            steps=[],
        ),
    )


# --- ordering -------------------------------------------------------------------------


def test_entries_are_ordered_by_when_they_were_recorded() -> None:
    entries = timeline(_run())

    assert [e.at for e in entries] == sorted(e.at for e in entries)
    assert [e.kind for e in entries][:3] == [
        EntryKind.TRIGGER,
        EntryKind.STARTED,
        EntryKind.STEP_STARTED,
    ]
    assert entries[-1].kind is EntryKind.COMPLETED


def test_a_finding_is_placed_when_it_was_reported_not_when_it_happened() -> None:
    """The window began five minutes before the alert. Placing the Finding there
    would put an anomaly on the timeline before anybody had noticed it - a
    timeline that reads as if the system knew things before it did."""
    entries = timeline(_run())
    (argus,) = [e for e in entries if e.kind is EntryKind.FINDING]

    assert argus.at == _at(12.0)
    assert argus.at >= entries[0].at, "a Finding before the trigger that started the run"
    assert "over " in argus.summary, "the window it covers is not on the entry"


def test_records_at_one_instant_keep_record_order() -> None:
    """Argus finished and Lethe started at the same second, and Argus's Finding
    was reported then too. A sort that was not stable could emit Lethe's start
    before Argus's finish, or the Finding before the step that produced it."""
    entries = [e for e in timeline(_run()) if e.at == _at(12.0)]

    assert [(e.kind, e.actor) for e in entries] == [
        (EntryKind.STEP_FINISHED, "argus"),
        (EntryKind.STEP_STARTED, "lethe"),
        (EntryKind.FINDING, "argus"),
    ]


# --- what is on it --------------------------------------------------------------------


def test_a_degraded_finding_says_the_agent_could_not_look() -> None:
    """A partial run is visibly partial on the timeline, not a quiet gap."""
    entries = timeline(_run())
    (degraded,) = [e for e in entries if e.kind is EntryKind.DEGRADED]

    assert degraded.actor == "lethe"
    assert "could not look" in degraded.summary


def test_every_record_appears_exactly_once() -> None:
    run = _run()
    entries = timeline(run)

    refs = [e.ref for e in entries if e.ref is not None]
    assert len(refs) == len(set(refs)), "a record appears twice"
    assert {str(f.id) for f in run.findings} <= set(refs)
    assert str(run.verdict.id) in refs  # type: ignore[union-attr]
    assert sum(1 for e in entries if e.kind is EntryKind.STEP_STARTED) == 2
    assert sum(1 for e in entries if e.kind is EntryKind.STEP_FINISHED) == 2


def test_a_run_still_going_has_no_completion_and_no_verdict() -> None:
    """Lifecycle moments appear only once they have happened."""
    running = _run().model_copy(
        update={
            "state": InvestigationState.RUNNING,
            "completed_at": None,
            "verdict": None,
        }
    )

    kinds = {e.kind for e in timeline(running)}

    assert EntryKind.COMPLETED not in kinds
    assert EntryKind.VERDICT not in kinds
    assert EntryKind.STARTED in kinds


def test_the_timeline_is_deterministic() -> None:
    """A pure function of the Investigation. Two calls, one answer."""
    run = _run()

    assert timeline(run) == timeline(run)


# --- the endpoint ---------------------------------------------------------------------


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, InMemoryInvestigationStore]]:
    monkeypatch.setenv("PANTHEON_API_TOKENS", "reader:viewer@acme=t1")
    get_settings.cache_clear()
    _principals.cache_clear()
    store = InMemoryInvestigationStore()
    try:
        with TestClient(create_app(investigation_store=store)) as test_client:
            yield test_client, store
    finally:
        get_settings.cache_clear()
        _principals.cache_clear()


@pytest.mark.asyncio
async def test_the_endpoint_serves_the_timeline_in_order(
    client: tuple[TestClient, InMemoryInvestigationStore],
) -> None:
    test_client, store = client
    run = _run()
    await store.save(run)

    response = test_client.get(
        f"/investigations/{run.id}/timeline", headers={"Authorization": "Bearer t1"}
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["kind"] == "trigger"
    assert rows[-1]["kind"] == "completed"
    assert rows == sorted(rows, key=lambda row: row["at"])


@pytest.mark.asyncio
async def test_another_tenants_timeline_is_a_404(
    client: tuple[TestClient, InMemoryInvestigationStore],
) -> None:
    """Same rule as the read beside it: existence is the disclosure."""
    test_client, store = client
    theirs = _run(tenant="globex")
    await store.save(theirs)

    response = test_client.get(
        f"/investigations/{theirs.id}/timeline", headers={"Authorization": "Bearer t1"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"no investigation {theirs.id}"


def test_the_timeline_needs_a_token(client: tuple[TestClient, InMemoryInvestigationStore]) -> None:
    test_client, _ = client

    assert test_client.get(f"/investigations/{uuid4()}/timeline").status_code == 401


# --- the records a real run adds beyond findings -----------------------------------


def test_consultations_and_credential_events_are_on_the_timeline() -> None:
    """A model consultation and a credential grant are things that happened, and
    a timeline that showed findings only would read as if the agents worked
    for free and without keys."""
    from core.contracts.credentials import AuditEntry, AuditEvent
    from core.contracts.llm import (
        ModelDescriptor,
        ModelRequirements,
        ResolutionRecord,
        ResolutionStep,
    )

    run = _run().model_copy(
        update={
            "resolutions": [
                ResolutionRecord(
                    id=uuid4(),
                    requested_by="hermes",
                    requirements=ModelRequirements(),
                    matched_step=ResolutionStep.TIER_DEFAULT,
                    chosen=ModelDescriptor(provider_id="groq", model_id="llama-3.3-70b"),
                    resolved_at=_at(8.0),
                )
            ],
            "audit": [
                AuditEntry(
                    id=uuid4(),
                    at=_at(4.0),
                    event=AuditEvent.GRANTED,
                    actor="cerberus",
                    detail="argus may read prometheus",
                ),
                AuditEntry(
                    id=uuid4(), at=_at(4.5), event=AuditEvent.LEASE_MINTED, actor="cerberus"
                ),
            ],
        }
    )

    entries = timeline(run)
    (consultation,) = [e for e in entries if e.kind is EntryKind.CONSULTATION]
    credentials = [e for e in entries if e.kind is EntryKind.CREDENTIAL]

    assert consultation.actor == "hermes"
    assert "groq/llama-3.3-70b" in consultation.summary
    assert "tier_default" in consultation.summary
    assert [c.summary for c in credentials] == [
        "granted: argus may read prometheus",
        "lease_minted",  # no detail: the event alone, not "lease_minted: "
    ]


def test_a_trigger_with_no_title_still_opens_the_timeline() -> None:
    """A webhook can arrive untitled. The entry says what kind arrived rather
    than rendering an empty line."""
    untitled = _run().model_copy(
        update={
            "trigger": Trigger(
                kind=TriggerKind.WEBHOOK, received_at=_at(0.0), source="github", title=""
            )
        }
    )

    first = timeline(untitled)[0]

    assert first.kind is EntryKind.TRIGGER
    assert first.summary == "webhook received"


def test_a_finding_with_no_window_carries_no_window_clause() -> None:
    """Some Findings are about a moment, not a span. "(over None to None)" is
    the clause a naive formatter would print."""
    run = _run()
    windowless = run.findings[0].model_copy(update={"window_start": None, "window_end": None})
    run = run.model_copy(update={"findings": [windowless]})

    (entry,) = [e for e in timeline(run) if e.kind is EntryKind.FINDING]

    assert "over" not in entry.summary
    assert "None" not in entry.summary
