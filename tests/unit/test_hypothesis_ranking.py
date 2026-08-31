"""Ranking Findings into candidate causes, and refusing to name what it cannot.

The interesting tests here are the refusals. There are five scenarios with
declared ground truth and the answer sheet is in the repository, so a mapping
that named all five would be one fitted to it - and it would pass every test a
careless author wrote.

`docs/zeus-predictions/01-hypothesis-ranking.md` commits which two must come
back UNKNOWN, written before the module existed.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.contracts.evidence import (
    Evidence,
    EvidenceSource,
    LogClusterPayload,
    MetricWindowPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity
from core.contracts.root_cause import HypothesisStatus, RootCauseCategory
from core.orchestrator.hypotheses import (
    BASE_CONFIDENCE,
    MAX_CONFIDENCE,
    SIGNALS,
    leading,
    rank,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

MEMORY = "pantheon_pod_memory_working_set_bytes"
DISK = "pantheon_node_disk_used_bytes / pantheon_node_disk_total_bytes"
CI = "pantheon_ci_pipeline_failure_ratio"
CPU = "pantheon_pod_cpu_cores"
LATENCY = "pantheon_http_request_duration_seconds"
ERRORS = next(
    metric for metric in SIGNALS if metric.startswith("sum by (service) (rate(pantheon_http")
)


def _ref(kind: str = "pod", name: str = "checkout-7f9") -> ResourceRef:
    return ResourceRef(kind=kind, name=name)


def _metric_finding(
    metric: str,
    *,
    agent: str = "argus",
    subject: ResourceRef | None = None,
    title: str | None = None,
) -> Finding:
    """A Finding shaped the way Argus builds one."""
    where = subject if subject is not None else _ref()
    return Finding(
        id=uuid4(),
        agent=agent,
        kind=FindingKind.ANOMALY,
        title=title or f"{metric} crossed its threshold",
        severity=Severity.MEDIUM,
        confidence=0.8,
        detected_at=NOW,
        window_start=NOW - timedelta(minutes=10),
        window_end=NOW,
        subject=where,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="prometheus", query=metric),
                observed_at=NOW,
                summary=f"{metric} crossed",
                subject=where,
                payload=MetricWindowPayload(metric=metric, samples=[]),
            )
        ],
    )


def _log_finding(subject: ResourceRef | None = None) -> Finding:
    """A Lethe-shaped Finding: real evidence, and no metric payload at all."""
    where = subject if subject is not None else _ref()
    return Finding(
        id=uuid4(),
        agent="lethe",
        kind=FindingKind.OBSERVATION,
        title="novel log pattern: pool exhausted",
        severity=Severity.MEDIUM,
        confidence=0.8,
        detected_at=NOW,
        window_start=NOW - timedelta(minutes=10),
        window_end=NOW,
        subject=where,
        evidence=[
            Evidence(
                id=uuid4(),
                source=EvidenceSource(connector="loki", query='{job="pantheon"}'),
                observed_at=NOW,
                summary="novel template",
                subject=where,
                payload=LogClusterPayload(template="pool exhausted <*>", occurrences=12),
            )
        ],
    )


# --- a clean window says nothing, and that is not UNKNOWN ---------------------------------


def test_a_clean_window_produces_no_hypothesis_at_all() -> None:
    """Prediction 2. UNKNOWN means something happened and could not be
    explained; nothing happening is not that, and reporting it would put an
    unexplained incident on every dashboard every five minutes."""
    assert rank([]) == []


def test_a_window_of_only_degraded_findings_produces_nothing() -> None:
    """A run that could not look is not a run that looked and found nothing.
    Ranking a DEGRADED Finding would turn "Loki was unreachable" into a cause.
    """
    degraded = Finding(
        id=uuid4(),
        agent="lethe",
        kind=FindingKind.DEGRADED,
        title="could not reach Loki",
        severity=Severity.MEDIUM,
        confidence=0.0,
        detected_at=NOW,
    )

    assert rank([degraded]) == []


# --- a naming signal proposes; a symptom never does ------------------------------------------


def test_memory_growth_names_a_memory_leak() -> None:
    """The metric is resident memory. Sustained growth without release is what
    the phrase means - semantics, not a heuristic fitted to a corpus."""
    (hypothesis,) = rank([_metric_finding(MEMORY)])

    assert hypothesis.category is RootCauseCategory.MEMORY_LEAK
    assert hypothesis.reasoning is not None
    assert "resident memory" in hypothesis.reasoning


def test_disk_and_ci_ratios_name_their_categories() -> None:
    assert rank([_metric_finding(DISK, subject=_ref("node", "node-1"))])[0].category is (
        RootCauseCategory.DISK_EXHAUSTION
    )
    assert rank([_metric_finding(CI, subject=_ref("service", "checkout"))])[0].category is (
        RootCauseCategory.FLAKY_TEST
    )


def test_errors_and_latency_alone_are_unknown() -> None:
    """Prediction 1's second half, and the honest report: Zeus cannot conclude
    `bad_deployment`, because nothing in this system reports deployments."""
    hypotheses = rank([_metric_finding(ERRORS), _metric_finding(LATENCY)])

    (hypothesis,) = hypotheses
    assert hypothesis.category is RootCauseCategory.UNKNOWN
    assert hypothesis.status is HypothesisStatus.INCONCLUSIVE


def test_cpu_alone_is_unknown_and_not_resource_contention() -> None:
    """High CPU on one pod is not contention. Contention is a claim about
    neighbours, and nothing here knows which pods share a node."""
    (hypothesis,) = rank([_metric_finding(CPU)])

    assert hypothesis.category is RootCauseCategory.UNKNOWN
    assert hypothesis.reasoning is not None
    assert "neighbours" in hypothesis.reasoning


def test_an_unknown_carries_the_evidence_that_could_not_be_explained() -> None:
    """Prediction 3. An UNKNOWN with the Findings attached is a lead; one with
    nothing attached is a shrug."""
    errors = _metric_finding(ERRORS)
    latency = _metric_finding(LATENCY)

    (hypothesis,) = rank([errors, latency])

    assert set(hypothesis.supporting_finding_ids) == {errors.id, latency.id}


def test_a_finding_with_no_metric_cannot_name_a_cause() -> None:
    """A log-cluster Finding corroborates. The safe direction: a new evidence
    kind cannot start naming causes by being unrecognised."""
    (hypothesis,) = rank([_log_finding()])

    assert hypothesis.category is RootCauseCategory.UNKNOWN


def test_a_symptom_beside_a_naming_signal_does_not_propose_its_own() -> None:
    """The whole rule in one test. Latency does not become a second hypothesis
    just because it fired alongside a real one."""
    hypotheses = rank([_metric_finding(MEMORY), _metric_finding(LATENCY)])

    assert [h.category for h in hypotheses] == [RootCauseCategory.MEMORY_LEAK]


# --- confidence never exceeds the evidence ---------------------------------------------------


def test_one_signal_scores_the_base_and_no_more() -> None:
    """Prediction 4. One metric crossing a threshold is a reason to look, not a
    conclusion."""
    (hypothesis,) = rank([_metric_finding(MEMORY)])

    assert hypothesis.confidence == BASE_CONFIDENCE


def test_an_independent_corroboration_raises_it() -> None:
    """The control. A confidence that never moved would make the whole
    calculation decoration."""
    alone = rank([_metric_finding(MEMORY)])[0]
    corroborated = rank([_metric_finding(MEMORY), _log_finding()])[0]

    assert corroborated.confidence > alone.confidence


def test_the_same_observation_reported_twice_is_not_corroboration() -> None:
    """Two Findings from one agent about one metric are one observation
    reported twice. Counting them separately would let a noisy detector talk
    itself into certainty."""
    once = rank([_metric_finding(MEMORY)])[0]
    twice = rank([_metric_finding(MEMORY), _metric_finding(MEMORY)])[0]

    assert twice.confidence == once.confidence


def test_corroboration_about_another_subject_does_not_count() -> None:
    """Otherwise latency on an unrelated service raises confidence in a memory
    leak somewhere else - which is how a ranker becomes more certain the busier
    the cluster is."""
    elsewhere = _metric_finding(LATENCY, subject=_ref("pod", "payments-1a2"))

    with_it = rank([_metric_finding(MEMORY), elsewhere])[0]

    assert with_it.confidence == BASE_CONFIDENCE


def test_nothing_reaches_certainty() -> None:
    """1.0 claims no further evidence could change the answer, and nothing here
    has tested a hypothesis against a counterfactual."""
    crowd = [_metric_finding(MEMORY, agent=f"agent-{index}") for index in range(12)]

    assert rank(crowd)[0].confidence <= MAX_CONFIDENCE


def test_a_proposal_is_not_a_confirmation() -> None:
    """Calling it SUPPORTED would mean a hypothesis is confirmed by the
    observation that suggested it."""
    (hypothesis,) = rank([_metric_finding(MEMORY)])

    assert hypothesis.status is HypothesisStatus.PROPOSED


# --- order independence ------------------------------------------------------------------------


def test_the_ranking_does_not_depend_on_the_order_findings_arrived() -> None:
    """Prediction 5, and the failure that hides: the input arrives in whichever
    order the agents finished, so a ranker keyed on iteration order passes every
    fixture written in one order and reorders itself in production."""
    findings = [
        _metric_finding(MEMORY),
        _metric_finding(DISK, subject=_ref("node", "node-1")),
        _metric_finding(CI, subject=_ref("service", "checkout")),
        _metric_finding(LATENCY),
    ]
    baseline = [h.category for h in rank(findings)]

    shuffled = list(findings)
    for seed in range(8):
        random.Random(seed).shuffle(shuffled)
        assert [h.category for h in rank(shuffled)] == baseline


def test_equal_confidence_hypotheses_are_ordered_by_name_not_by_arrival() -> None:
    """The tie-break has to be something other than insertion order, because
    insertion order is agent completion order, which is a race."""
    findings = [
        _metric_finding(DISK, subject=_ref("node", "node-1")),
        _metric_finding(MEMORY),
    ]

    categories = [h.category.value for h in rank(findings)]

    assert categories == sorted(categories)


# --- the leading hypothesis, and the honest absence of one --------------------------------------


def test_there_is_no_leader_when_nothing_was_proposed() -> None:
    """`Verdict.confidence` is defined as confidence in a leading hypothesis, so
    with none there is nothing to be confident about."""
    assert leading([]) is None


def test_a_tie_has_no_leader() -> None:
    """Picking one of two equally supported hypotheses is the ranker inventing a
    judgement it did not make."""
    tied = rank(
        [
            _metric_finding(MEMORY),
            _metric_finding(DISK, subject=_ref("node", "node-1")),
        ]
    )

    assert len(tied) == 2
    assert tied[0].confidence == tied[1].confidence
    assert leading(tied) is None


def test_a_clear_winner_leads() -> None:
    """The control. A `leading` that returned None for everything would make
    every Verdict confidence 0.0 and look exactly like honest uncertainty."""
    ranked = rank(
        [
            _metric_finding(MEMORY),
            _log_finding(),
            _metric_finding(DISK, subject=_ref("node", "node-1")),
        ]
    )

    top = leading(ranked)
    assert top is not None
    assert top.category is RootCauseCategory.MEMORY_LEAK


# --- the mapping is honest about what it can reach ------------------------------------------------


def test_every_naming_signal_is_a_metric_argus_actually_watches() -> None:
    """A signal keyed on a metric nothing produces is a rule that can never
    fire - and it would read as coverage."""
    from agents.anomaly.agent import SERIES

    watched = {spec.query for spec in SERIES.values()}
    unwatched = sorted(metric for metric in SIGNALS if metric not in watched)

    assert not unwatched, f"{unwatched} are ranked on and never measured"


def test_every_metric_argus_watches_has_a_declared_entitlement() -> None:
    """A metric absent from SIGNALS and one present with `names=None` are both
    "proposes nothing", and only the second says somebody decided it."""
    from agents.anomaly.agent import SERIES

    undeclared = sorted(spec.query for spec in SERIES.values() if spec.query not in SIGNALS)

    assert not undeclared, f"{undeclared} are measured with no decision about what they mean"


def test_the_two_unreachable_categories_are_named_by_nothing() -> None:
    """Committed as misses in docs/zeus-predictions before this module existed.

    `bad_deployment` needs a deployment event and `resource_contention` needs
    topology; both connectors are stubs. Asserted so that wiring one up without
    revisiting this file fails here rather than silently changing what Zeus
    concludes.
    """
    named = {signal.names for signal in SIGNALS.values() if signal.names is not None}

    assert RootCauseCategory.BAD_DEPLOYMENT not in named
    assert RootCauseCategory.RESOURCE_CONTENTION not in named


# --- dissent: what the leading claim does not account for -----------------------------------


def _verdict(findings: list[Finding]):  # type: ignore[no-untyped-def]
    from core.contracts.plan import PlanStep, StepStatus
    from core.orchestrator import aggregator

    step = PlanStep(
        agent="argus",
        reason="an alert names metrics",
        status=StepStatus.COMPLETE,
    )
    return aggregator.aggregate(uuid4(), findings, [step])


def test_a_unanimous_run_records_no_dissent() -> None:
    """A dissent that fired on a run with one candidate would be noise, and
    noise on every verdict is how a field stops being read."""
    verdict = _verdict([_metric_finding(MEMORY), _log_finding()])

    assert len(verdict.hypotheses) == 1
    assert verdict.dissent == []


def test_a_competing_candidate_is_recorded_with_the_agents_behind_it() -> None:
    """A reader told "memory leak, 0.65" has no way to know two of the five
    findings pointed at disk. That omission is the difference between a
    conclusion and a summary of the majority.
    """
    disk = _metric_finding(DISK, agent="argus", subject=_ref("node", "node-1"))
    verdict = _verdict([_metric_finding(MEMORY), _log_finding(), disk])

    (objection,) = verdict.dissent
    assert objection.category is RootCauseCategory.DISK_EXHAUSTION
    assert objection.agents == ["argus"]
    assert objection.finding_ids == [disk.id]
    assert objection.confidence == BASE_CONFIDENCE


def test_a_tie_records_no_dissent_because_nothing_leads() -> None:
    """Two tied candidates are a run that reached no conclusion, not a majority
    with objectors. Calling one of two equals "the leader" would be the
    aggregator inventing the judgement `leading` deliberately refused."""
    verdict = _verdict(
        [_metric_finding(MEMORY), _metric_finding(DISK, subject=_ref("node", "node-1"))]
    )

    assert len(verdict.hypotheses) == 2
    assert verdict.confidence == 0.0
    assert verdict.dissent == [], "a tie has no leader, so there is nothing to dissent from"


def test_the_contract_refuses_dissent_with_nothing_leading() -> None:
    """Asserted on the contract, not only on the aggregator. A second producer
    of Verdicts would otherwise be free to write the shape this one refuses."""
    import pytest
    from pydantic import ValidationError

    from core.contracts.verdict import Dissent, Verdict

    with pytest.raises(ValidationError, match="nothing to dissent from"):
        Verdict(
            id=uuid4(),
            investigation_id=uuid4(),
            summary="two candidates, neither leading",
            hypotheses=[],
            confidence=0.0,
            dissent=[Dissent(category=RootCauseCategory.MEMORY_LEAK, confidence=0.55)],
            decided_at=NOW,
            steps=[],
        )


def test_dissent_names_every_agent_that_contributed_to_it() -> None:
    """Unattributed disagreement is disagreement nobody can follow up."""
    disk = _metric_finding(DISK, agent="argus", subject=_ref("node", "node-1"))
    corroborating = _log_finding(subject=_ref("node", "node-1"))
    leader = [_metric_finding(MEMORY), _log_finding(), _metric_finding(MEMORY, agent="hermes")]

    verdict = _verdict([*leader, disk, corroborating])

    (objection,) = verdict.dissent
    assert objection.agents == ["argus", "lethe"]
