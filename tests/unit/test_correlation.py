"""What correlation groups, and the far longer list of what it refuses to claim.

It says these Findings are about one resource in one window. That is a fact,
checkable from the Findings themselves. It does not say they share a cause -
"the memory anomaly caused the OOM" and the reverse are both consistent with
co-occurrence, and `simulator/scenarios/*.yaml` carries ground truth for exactly
that field, so an invented ordering would be scored as though it were reasoning.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agents._base.base_agent import AgentContext, BaseAgent
from core.contracts.evidence import (
    BaselineEstimator,
    Evidence,
    EvidenceSource,
    MetricSample,
    MetricWindowPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity
from core.orchestrator.correlation import correlate

END = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

#: Distinguishes "use the default subject" from "genuinely unattributed".
#: Without it, `subject=None` selected the default pod and the unattributed
#: case could not be expressed - the test asserted a claim its own fixture
#: prevented it from making.
_DEFAULT = ResourceRef(kind="pod", name="checkout-7f9")


def _evidence() -> Evidence:
    return Evidence(
        id=uuid4(),
        source=EvidenceSource(connector="prometheus", query="up", collected_at=END),
        observed_at=END,
        summary="something moved",
        payload=MetricWindowPayload(
            metric="up",
            samples=[MetricSample(at=END, value=1.0)],
            estimator=BaselineEstimator.NOT_APPLICABLE,
        ),
    )


def _finding(
    *,
    agent: str = "argus",
    subject: ResourceRef | None = _DEFAULT,
    kind: FindingKind = FindingKind.ANOMALY,
    starts: datetime | None = None,
    ends: datetime | None = None,
    evidence: bool = True,
) -> Finding:
    return Finding(
        id=uuid4(),
        agent=agent,
        kind=kind,
        title="something",
        severity=Severity.MEDIUM,
        confidence=0.5,
        detected_at=END,
        window_start=starts if starts is not None else END - timedelta(minutes=30),
        window_end=ends if ends is not None else END,
        subject=subject,
        evidence=[_evidence()] if evidence else [],
    )


# --- what it groups ---------------------------------------------------------------


def test_two_agents_reporting_on_one_pod_are_grouped() -> None:
    """The case the whole thing exists for: a memory anomaly and an OOM pattern
    on the same pod, in the same window, reported by different agents."""
    findings = [_finding(agent="argus"), _finding(agent="lethe")]

    correlations = correlate(findings)

    assert len(correlations) == 1
    group = correlations[0]
    assert group.kind is FindingKind.CORRELATION
    assert group.agent == "zeus"
    assert set(group.related) == {f.id for f in findings}
    assert "agent:argus" in group.tags and "agent:lethe" in group.tags


def test_findings_about_different_resources_are_not_grouped() -> None:
    """The control. Grouping on anything would make every incident one blob."""
    findings = [
        _finding(subject=ResourceRef(kind="pod", name="checkout-7f9")),
        _finding(subject=ResourceRef(kind="pod", name="payments-b31")),
    ]

    assert correlate(findings) == []


def test_a_pod_and_its_service_are_not_joined() -> None:
    """`ResourceRef` carries no parent link, so this cannot be known here.

    Guessing it from a name prefix works until a pod is named after something
    else. The limitation is real and stated rather than papered over with a
    heuristic that fails silently.
    """
    findings = [
        _finding(agent="argus", subject=ResourceRef(kind="pod", name="checkout-7f9")),
        _finding(agent="lethe", subject=ResourceRef(kind="service", name="checkout")),
    ]

    assert correlate(findings) == []


def test_findings_in_disjoint_windows_are_not_grouped() -> None:
    """Same pod, different hours, unrelated events."""
    findings = [
        _finding(starts=END - timedelta(hours=4), ends=END - timedelta(hours=3)),
        _finding(starts=END - timedelta(minutes=30), ends=END),
    ]

    assert correlate(findings) == []


def test_a_lone_finding_is_not_a_correlation() -> None:
    """One Finding co-occurs with nothing, and reporting it would double every
    incident's output while adding nothing.

    There is no MIN_GROUP constant to assert against. There was, and it could
    not fail: overlap is symmetric, so a group is never size one and the
    separate "needs two" check was a second expression of a rule the overlap
    filter already enforced.
    """
    assert correlate([_finding()]) == []
    assert correlate([_finding(), _finding(subject=ResourceRef(kind="pod", name="other"))]) == []


def test_nothing_co_occurring_is_a_result_not_a_failure() -> None:
    """An investigation where each Finding stands alone is a legitimate outcome
    and must not be dressed up as one where they connect."""
    assert correlate([]) == []


# --- what it refuses to claim ------------------------------------------------------


def test_a_correlation_says_it_is_not_causation() -> None:
    """The boundary. A reader must not take a group for a diagnosis."""
    group = correlate([_finding(agent="argus"), _finding(agent="lethe")])[0]

    assert "confidence:co-occurrence-is-not-causation" in group.tags
    assert group.rationale is not None
    assert "not claimed" in group.rationale
    assert "nothing here ranks candidate causes" in group.rationale


def test_a_correlation_proposes_no_ordering() -> None:
    """ "A caused B" and "B caused A" are both consistent with co-occurrence."""
    first, second = _finding(agent="argus"), _finding(agent="lethe")

    group = correlate([first, second])[0]

    assert set(group.related) == {first.id, second.id}
    assert group.severity is Severity.MEDIUM, (
        "a severity that ranked the group would be asserting which of these matters"
    )


def test_a_degraded_finding_is_never_correlated() -> None:
    """It reports that an agent could not look. Grouping it with an observation
    would assert that a failure to measure co-occurred with the thing it failed
    to measure."""
    findings = [
        _finding(agent="argus"),
        _finding(agent="lethe", kind=FindingKind.DEGRADED, evidence=False),
    ]

    assert correlate(findings) == []


def test_unattributed_findings_are_not_grouped_with_each_other() -> None:
    """ "Neither of these names a resource" is not something they have in common.

    Grouping on it would correlate every unattributed Finding in a run with
    every other - which is exactly what Lethe used to produce before it learned
    to name a pod.
    """
    findings = [_finding(agent="argus", subject=None), _finding(agent="lethe", subject=None)]

    assert correlate(findings) == []


# --- the shape of the group --------------------------------------------------------


def test_a_correlation_cites_evidence_from_its_members() -> None:
    """A Finding with none is inadmissible, and a correlation's support is the
    observations it links."""
    group = correlate([_finding(agent="argus"), _finding(agent="lethe")])[0]

    assert group.evidence, "a correlation with no evidence would not validate"


def test_the_window_spans_every_member() -> None:
    early = _finding(
        agent="argus", starts=END - timedelta(hours=1), ends=END - timedelta(minutes=20)
    )
    late = _finding(agent="lethe", starts=END - timedelta(minutes=30), ends=END)

    group = correlate([early, late])[0]

    assert group.window_start == early.window_start
    assert group.window_end == late.window_end


def test_the_same_group_produces_the_same_id_twice() -> None:
    """Deterministic in the members, so re-running an investigation does not
    produce a new correlation id for the same conclusion."""
    findings = [_finding(agent="argus"), _finding(agent="lethe")]

    assert correlate(findings)[0].id == correlate(findings)[0].id


def test_the_id_changes_when_the_membership_does() -> None:
    """The control. A constant id would pass the test above."""
    first, second, third = (
        _finding(agent="argus"),
        _finding(agent="lethe"),
        _finding(agent="hermes"),
    )

    assert correlate([first, second])[0].id != correlate([first, second, third])[0].id


def test_a_finding_with_no_window_still_correlates() -> None:
    """Refusing would silently drop a whole agent the day one stops setting the
    field - which reads as "these never co-occur" rather than as a missing value."""
    findings = [
        _finding(agent="argus"),
        _finding(agent="lethe", starts=None, ends=None),
    ]
    findings[1] = findings[1].model_copy(update={"window_start": None, "window_end": None})

    assert len(correlate(findings)) == 1


@pytest.mark.asyncio
async def test_an_investigation_carries_its_correlations() -> None:
    """Wired into the run, not merely importable. Correlation reads what ALL the
    agents produced, so it cannot run per-step."""
    from core.bus import InMemoryEventBus
    from core.contracts.investigation import Trigger, TriggerKind
    from core.orchestrator import dispatcher, register_implemented
    from core.orchestrator.router import investigate
    from core.store.investigations import InMemoryInvestigationStore

    register_implemented()
    original = dict(dispatcher.AGENTS)
    try:
        dispatcher.AGENTS.clear()
        dispatcher.register("argus", _ReportsOnAPod)
        dispatcher.register("lethe", _ReportsOnAPodToo)

        investigation = await investigate(
            Trigger(
                kind=TriggerKind.ALERT,
                received_at=END,
                source="alertmanager",
                title="t",
                payload={"alerts": [{"labels": {"alertname": "X"}}]},
            ),
            store=InMemoryInvestigationStore(),
            bus=InMemoryEventBus(),
        )
    finally:
        dispatcher.AGENTS.clear()
        dispatcher.AGENTS.update(original)

    groups = [f for f in investigation.findings if f.kind is FindingKind.CORRELATION]
    assert len(groups) == 1, [f.title for f in investigation.findings]
    assert len(groups[0].related) == 2


class _ReportsOnAPod(BaseAgent):
    """Reports one Finding about a fixed pod, so two of these co-occur."""

    domain = "anomaly"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        return [_finding(agent=self.codename)]


class _ReportsOnAPodToo(_ReportsOnAPod):
    domain = "log_clustering"
