"""Flow 1, end to end: alert -> plan -> dispatch -> detect -> verdict.

Both directions, and the negative one is the point. A pipeline that produces an
Investigation for anything would pass every positive test here and be worse than
no pipeline, so a clean baseline run must produce **no Investigation at all** -
not an empty one, not a quiet one.

WHAT "PERSISTS" IS ASSERTED TO MEAN
------------------------------------
The Investigation is read back through a **second store instance on a fresh
connection**, after the run has finished. A dict would pass a test that reads
through the same object it wrote to; only a row in Postgres passes this one.

Run with:  make test-flow-one

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest

from core.bus import InMemoryEventBus
from core.config import get_settings
from core.contracts.investigation import (
    Investigation,
    InvestigationState,
    Trigger,
    TriggerKind,
)
from core.contracts.plan import PlanStep, StepStatus
from core.contracts.verdict import Verdict
from core.orchestrator import for_manifest, investigate, register_implemented
from core.store.investigations import PostgresInvestigationStore
from simulator.alerting import GATE_TICK_SECONDS, gate_speed
from simulator.metrics_generator import MetricsGenerator
from simulator.runner import ScenarioRunner
from simulator.scenario import load
from tests.unit.test_alert_rules import rule_seconds
from tests.unit.test_alert_rules import rules as alerting_rules

pytestmark = pytest.mark.integration

SETTINGS = get_settings()
ALERTMANAGER = SETTINGS.alertmanager.base
SETTLE_SECONDS = 20.0
BASELINE_WALL = 240.0

#: The scenario whose alert drives the positive case, and the metric its fault
#: actually moves. Both are asserted: an Investigation that exists but cites the
#: wrong series is not a working flow.
SCENARIO = "bad_deploy_5xx"
EXPECTED_METRIC = "error_ratio"


def _alert_payload(scenario: str, status: str = "firing") -> dict[str, Any]:
    """What Alertmanager sends, shaped as the receiver expects."""
    return {
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "CheckoutErrorRateHigh",
                    "scenario": scenario,
                    "severity": "critical",
                },
                "annotations": {"summary": "error rate is up"},
            }
        ],
        "commonLabels": {"alertname": "CheckoutErrorRateHigh", "scenario": scenario},
    }


def _trigger(payload: dict[str, Any]) -> Trigger:
    return Trigger(
        kind=TriggerKind.ALERT,
        received_at=datetime.now(UTC),
        source="alertmanager",
        title="CheckoutErrorRateHigh firing",
        payload=payload,
    )


def _alertmanager_is_quiet() -> bool:
    """No alert is firing right now."""
    response = httpx.get(f"{ALERTMANAGER}/api/v2/alerts", timeout=10.0)
    response.raise_for_status()
    return not [a for a in response.json() if a.get("status", {}).get("state") == "active"]


@pytest.mark.asyncio
async def test_an_alert_produces_a_complete_investigation(stack: None) -> None:
    """The positive case, through every stage.

    The scenario runs first so there is a real fault in the window Zeus will
    hand to Argus. The alert is then delivered as Alertmanager would deliver it.
    """
    register_implemented()
    scenario = load(SCENARIO)
    speed = gate_speed(
        scenario,
        {r["labels"]["scenario"]: rule_seconds(r) for r in alerting_rules()}[SCENARIO],
        GATE_TICK_SECONDS,
    )

    MetricsGenerator().reset()
    time.sleep(SETTLE_SECONDS)
    report = ScenarioRunner(tick_seconds=GATE_TICK_SECONDS, wall_paced=True).run(
        scenario, speed=speed, send_pipelines=False
    )
    assert not report.degraded, "the scenario run itself was degraded"

    store = PostgresInvestigationStore()
    bus = InMemoryEventBus()
    try:
        investigation = await investigate(
            _trigger(_alert_payload(SCENARIO)), store=store, bus=bus, toolset=for_manifest
        )
    finally:
        await store.close()

    # -- the run reached a conclusion -------------------------------------
    assert investigation.state is InvestigationState.COMPLETED
    assert investigation.scenario == SCENARIO, "the run cannot be scored without its scenario"
    assert investigation.started_at and investigation.completed_at

    # -- the plan ran, and says so ----------------------------------------
    assert [s.agent for s in investigation.plan] == ["argus"]
    step = investigation.plan[0]
    assert step.status is StepStatus.COMPLETE, f"argus did not complete: {step.status}"
    assert step.reason, "a step with no reason cannot be reviewed"
    assert step.started_at and step.finished_at

    # -- the verdict cites the finding, and the finding cites the series ---
    verdict = investigation.verdict
    assert verdict is not None, "a completed investigation with no verdict"
    assert verdict.steps, "a verdict without steps cannot tell nobody-looked from nothing-found"
    assert verdict.contributing_findings, "the verdict cites no findings"

    cited = [f for f in verdict.contributing_findings if f"metric:{EXPECTED_METRIC}" in f.tags]
    assert cited, (
        f"{SCENARIO} moves {EXPECTED_METRIC} and no cited finding names it: "
        f"{[f.title for f in verdict.contributing_findings]}"
    )
    for finding in cited:
        assert finding.agent == "argus"
        assert finding.evidence, "an anomaly with no evidence is inadmissible"
        evidence = finding.evidence[0]
        assert evidence.subject is not None and evidence.subject.name
        assert evidence.source.query, "the evidence does not cite the query that produced it"

    # -- and it refuses to be a diagnosis ---------------------------------
    assert verdict.hypotheses == [], (
        "the verdict proposed a hypothesis; nothing here ranks candidate causes"
    )
    assert verdict.confidence == 0.0
    assert "not an explanation" in verdict.summary

    # -- the lifecycle was emitted ----------------------------------------
    emitted = [e.event.type for e in bus.published]
    assert emitted == [
        "investigation_started",
        "step_started",
        "step_finished",
        "verdict_ready",
        "investigation_completed",
    ], emitted

    # -- and it persisted, read back on a NEW connection -------------------
    fresh = PostgresInvestigationStore()
    try:
        stored = await fresh.get(investigation.id)
    finally:
        await fresh.close()

    assert stored is not None, (
        "the investigation was not retrievable from a second store instance, so it "
        "never left the process"
    )
    assert stored.id == investigation.id
    assert stored.state is InvestigationState.COMPLETED
    assert stored.verdict is not None
    assert len(stored.findings) == len(investigation.findings)


@pytest.mark.asyncio
async def test_a_clean_baseline_fires_no_alert_and_so_starts_nothing(
    stack: None,
) -> None:
    """The negative case: no alert, therefore no Investigation.

    Asserted at the Alertmanager end rather than by calling Zeus with nothing.
    Zeus starts an Investigation when a trigger arrives - that is its job - so
    testing it with no trigger would assert nothing about the flow. What has to
    be true is that a clean cluster produces no trigger in the first place.
    """
    store = PostgresInvestigationStore()
    try:
        before = {i.id for i in await store.recent(limit=100)}

        MetricsGenerator().reset()
        time.sleep(SETTLE_SECONDS)
        report = ScenarioRunner(tick_seconds=GATE_TICK_SECONDS, wall_paced=True).baseline(
            speed=630.0, simulated_seconds=630.0 * BASELINE_WALL
        )
        assert not report.degraded, "the baseline run itself was degraded"

        assert _alertmanager_is_quiet(), (
            "a clean baseline fired an alert, so the flow would have opened an "
            "investigation into nothing"
        )

        after = {i.id for i in await store.recent(limit=100)}
    finally:
        await store.close()

    assert after == before, (
        f"{len(after - before)} investigation(s) appeared during a clean baseline run. "
        "No alert fired, so nothing should have been opened."
    )


@pytest.mark.asyncio
async def test_the_store_round_trips_a_verdict_through_jsonb(stack: None) -> None:
    """Write one, read it back on a fresh connection, compare.

    Iterating whatever the table happens to hold would pass on an empty one,
    which is a test that cannot fail. This writes a known Investigation with a
    nested Verdict and asserts the nesting survives - the part most likely to
    be quietly flattened by a serialisation change.
    """
    subject = Investigation(
        id=uuid4(),
        state=InvestigationState.COMPLETED,
        trigger=_trigger(_alert_payload(SCENARIO)),
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        plan=[PlanStep(agent="argus", reason="round trip", status=StepStatus.COMPLETE)],
        scenario=SCENARIO,
    )
    subject = subject.model_copy(
        update={
            "verdict": Verdict(
                id=uuid4(),
                investigation_id=subject.id,
                summary="round trip",
                hypotheses=[],
                confidence=0.0,
                decided_at=datetime.now(UTC),
                steps=subject.plan,
            )
        }
    )

    writer = PostgresInvestigationStore()
    try:
        await writer.save(subject)
    finally:
        await writer.close()

    reader = PostgresInvestigationStore()
    try:
        stored = await reader.get(subject.id)
    finally:
        await reader.close()

    assert stored is not None, "the row did not survive the write"
    assert stored.verdict is not None, "the nested verdict was lost in the round trip"
    assert stored.verdict.investigation_id == subject.id
    assert stored.plan[0].status is StepStatus.COMPLETE
    assert stored.scenario == SCENARIO
