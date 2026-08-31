"""Ranking correlated Findings into candidate root causes.

A SIGNAL THAT NAMES A CAUSE, AND A SIGNAL THAT IS A SYMPTOM
-------------------------------------------------------------
This is the whole design, and getting it wrong is how a ranker becomes a
category generator.

Three of Argus's six signals **name** a cause, because the metric *is* the thing
the category describes. `pantheon_pod_memory_working_set_bytes` is resident
memory, and sustained growth without release is what "memory leak" means. That
is semantics, not a heuristic fitted to a corpus.

Three do not. Errors rising says errors rose - it does not say a deployment
caused them. High CPU on one pod is not contention; contention is a claim about
*neighbours*, and nothing here knows which pods share a node. Latency is a
symptom of all five scenarios.

So a hypothesis is proposed **only** from a naming signal. A corroborating
signal raises confidence in a hypothesis already proposed and can never propose
one alone. With only corroborating signals the answer is `UNKNOWN`, which the
vocabulary carries specifically so that "we do not know" is statable rather than
absent.

WHAT THIS CANNOT CONCLUDE, AND WHY THAT IS REPORTED RATHER THAN FIXED
-----------------------------------------------------------------------
Two of the five scenarios with declared ground truth are unreachable:

* **`bad_deployment`** needs a deployment event. `connectors/gitlab` and
  `connectors/github` are Phase 4 stubs, so nothing in this system reports one.
* **`resource_contention`** needs topology - which pods share a node. The
  Kubernetes connector is a Go stub.

Both were predicted as misses in `docs/zeus-predictions/01-hypothesis-ranking.md`
BEFORE this module existed, precisely because the answer sheet is in the
repository and a mapping that got all five would have been fitted to it.

`UNKNOWN` CARRIES ITS EVIDENCE
-------------------------------
An `UNKNOWN` with the Findings attached is a lead: somebody reads "errors and
latency rose on checkout, and nothing here can say why" and knows where to look.
An `UNKNOWN` with nothing attached is a shrug.

A CLEAN WINDOW PRODUCES NOTHING, NOT `UNKNOWN`
------------------------------------------------
`UNKNOWN` means something happened and could not be explained. A quiet system
means nothing happened, and reporting `UNKNOWN` for it would put an unexplained
incident on every dashboard every five minutes.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from core.contracts.evidence import EvidenceKind
from core.contracts.finding import Finding, FindingKind
from core.contracts.root_cause import (
    HypothesisStatus,
    RootCauseCategory,
    RootCauseHypothesis,
)

_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/zeus/hypotheses")


@dataclass(frozen=True)
class Signal:
    """One observable, and what it is entitled to conclude.

    `names` is the point. A signal with `names=None` is corroborating: it is
    consistent with the hypothesis and cannot propose one, because being
    consistent with everything is being evidence for nothing.
    """

    metric: str
    names: RootCauseCategory | None
    #: Why this signal is entitled to name that category, in one sentence. Kept
    #: on the signal rather than in a comment, because it is what a reader needs
    #: at the moment they are asking whether to trust the conclusion.
    because: str


#: What Argus's metrics are entitled to conclude, keyed by the metric name it
#: puts on `MetricWindowPayload.metric`.
#:
#: Matched on the metric rather than on the Finding title. A title is prose that
#: changes when somebody improves the wording, and a ranker keyed on it would
#: quietly stop concluding anything - silently, because producing no hypothesis
#: is indistinguishable from having nothing to conclude.
SIGNALS: dict[str, Signal] = {
    "pantheon_pod_memory_working_set_bytes": Signal(
        metric="pantheon_pod_memory_working_set_bytes",
        names=RootCauseCategory.MEMORY_LEAK,
        because=(
            "the metric is resident memory, and sustained growth without release "
            "is what the phrase means"
        ),
    ),
    "pantheon_node_disk_used_bytes / pantheon_node_disk_total_bytes": Signal(
        metric="pantheon_node_disk_used_bytes / pantheon_node_disk_total_bytes",
        names=RootCauseCategory.DISK_EXHAUSTION,
        because="the metric is used over total, and approaching 1 is the definition",
    ),
    "pantheon_ci_pipeline_failure_ratio": Signal(
        metric="pantheon_ci_pipeline_failure_ratio",
        names=RootCauseCategory.FLAKY_TEST,
        because="the metric is the pipeline failure ratio",
    ),
    "pantheon_pod_cpu_cores": Signal(
        metric="pantheon_pod_cpu_cores",
        names=None,
        because=(
            "high CPU on one pod is not contention - contention is a claim about "
            "neighbours, and nothing here knows which pods share a node"
        ),
    ),
    "pantheon_http_request_duration_seconds": Signal(
        metric="pantheon_http_request_duration_seconds",
        names=None,
        because="latency rises under every one of these faults, so it separates none of them",
    ),
}

#: The error-ratio query, whose Findings corroborate and name nothing.
#:
#: Spelled out rather than omitted. A metric absent from `SIGNALS` and a metric
#: present with `names=None` are both "proposes nothing", and only the second
#: says somebody decided it.
_ERROR_RATIO = (
    'sum by (service) (rate(pantheon_http_requests_total{status="500"}[10s]))'
    " / (sum by (service) (rate(pantheon_http_requests_total[10s])) > 0)"
)
SIGNALS[_ERROR_RATIO] = Signal(
    metric=_ERROR_RATIO,
    names=None,
    because=(
        "errors rising says errors rose; it does not say a deployment caused them, "
        "and nothing in this system reports deployments"
    ),
)

#: Confidence for a hypothesis one naming signal proposed and nothing else
#: supports. Below the midpoint on purpose: one metric crossing a threshold is a
#: reason to look, not a conclusion.
BASE_CONFIDENCE = 0.55

#: Added per additional independent supporting Finding, capped below.
#:
#: Independent means a different agent or a different metric. Two Findings from
#: one agent about one metric are one observation reported twice, and counting
#: them separately would let a noisy detector talk itself into certainty.
CORROBORATION_STEP = 0.1

#: Nothing reaches this. 1.0 claims no further evidence could change the answer,
#: and nothing here has tested a hypothesis against a counterfactual - the
#: contradicting-evidence field exists and no agent populates it yet.
MAX_CONFIDENCE = 0.9


def rank(findings: list[Finding]) -> list[RootCauseHypothesis]:
    """Candidate root causes for these Findings, most confident first.

    Returns `[]` for a clean window. `UNKNOWN` means something happened that
    could not be explained; nothing happening is not that.

    Order-independent. The input arrives in whatever order the agents finished,
    so a ranking keyed on iteration order would pass every fixture written in
    one order and reorder itself in production.
    """
    substantive = [
        finding
        for finding in findings
        if finding.kind not in (FindingKind.DEGRADED, FindingKind.CORRELATION)
    ]
    if not substantive:
        return []

    by_category: dict[RootCauseCategory, list[Finding]] = defaultdict(list)
    corroborating: list[Finding] = []

    for finding in substantive:
        signal = _signal_of(finding)
        if signal is not None and signal.names is not None:
            by_category[signal.names].append(finding)
        else:
            corroborating.append(finding)

    if not by_category:
        return [_unexplained(substantive)]

    hypotheses = [
        _hypothesis(category, supporting, corroborating)
        for category, supporting in by_category.items()
    ]
    # Confidence first, then the category name. The tie-break is alphabetical
    # rather than insertion order because insertion order is agent completion
    # order, which is a race.
    return sorted(hypotheses, key=lambda h: (-h.confidence, h.category.value))


def _signal_of(finding: Finding) -> Signal | None:
    """The signal behind a Finding, read off its Evidence rather than its title.

    `None` when the Finding carries no metric - a log-cluster Finding, for
    instance. That is corroborating by default, which is the safe direction: a
    new evidence kind cannot start naming causes by being unrecognised.
    """
    for evidence in finding.evidence:
        if evidence.kind is not EvidenceKind.METRIC_WINDOW:
            continue
        metric = getattr(evidence.payload, "metric", None)
        if isinstance(metric, str):
            found = SIGNALS.get(metric)
            if found is not None:
                return found
    return None


def _hypothesis(
    category: RootCauseCategory,
    supporting: list[Finding],
    corroborating: list[Finding],
) -> RootCauseHypothesis:
    """One candidate, with its confidence derived from the evidence behind it."""
    relevant = [finding for finding in corroborating if _shares_subject(finding, supporting)]
    independent = _independent(supporting + relevant)
    confidence = min(BASE_CONFIDENCE + CORROBORATION_STEP * max(independent - 1, 0), MAX_CONFIDENCE)
    subject = supporting[0].subject
    naming = _signal_of(supporting[0])

    return RootCauseHypothesis(
        id=uuid5(_NAMESPACE, f"{category.value}:{subject.model_dump_json() if subject else ''}"),
        category=category,
        statement=_statement(category, supporting, subject),
        # PROPOSED, never SUPPORTED. Supporting evidence is what proposed it;
        # calling that "supported" would mean a hypothesis is confirmed by the
        # observation that suggested it.
        status=HypothesisStatus.PROPOSED,
        confidence=confidence,
        proposed_by="zeus",
        supporting_finding_ids=sorted({finding.id for finding in supporting + relevant}, key=str),
        subject=_describe(subject),
        reasoning=(
            f"{naming.because}. "
            f"{len(supporting)} finding(s) name it and {len(relevant)} corroborate."
            if naming is not None
            else None
        ),
    )


def _unexplained(findings: list[Finding]) -> RootCauseHypothesis:
    """`UNKNOWN`, carrying the evidence that could not be explained.

    The evidence is the difference between a lead and a shrug. Somebody reading
    "errors and latency rose on checkout, and nothing here can say why" knows
    where to look next.
    """
    subject = findings[0].subject
    reasons = sorted(
        {
            signal.because
            for signal in (_signal_of(finding) for finding in findings)
            if signal is not None
        }
    )
    return RootCauseHypothesis(
        id=uuid5(_NAMESPACE, f"unknown:{subject.model_dump_json() if subject else ''}"),
        category=RootCauseCategory.UNKNOWN,
        statement=(
            f"{len(findings)} finding(s) on {_describe(subject) or 'this system'} that "
            "nothing here can attribute to a cause"
        ),
        status=HypothesisStatus.INCONCLUSIVE,
        # Confidence in the CLAIM, and the claim is "we cannot say". It is not a
        # confidence of zero: zero would read as a hypothesis nobody believes,
        # and this one is being asserted deliberately.
        confidence=BASE_CONFIDENCE,
        proposed_by="zeus",
        supporting_finding_ids=sorted({finding.id for finding in findings}, key=str),
        subject=_describe(subject),
        reasoning=("; ".join(reasons) or "no signal here names a cause"),
    )


def _independent(findings: list[Finding]) -> int:
    """How many genuinely separate observations these are.

    Two Findings from one agent about one metric are one observation reported
    twice. Counting them separately would let a noisy detector talk itself into
    certainty.
    """
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        signal = _signal_of(finding)
        seen.add((finding.agent, signal.metric if signal else finding.kind.value))
    return len(seen)


def _shares_subject(finding: Finding, supporting: list[Finding]) -> bool:
    """Whether a corroborating Finding is about the same thing.

    Without this, latency on an unrelated service would raise confidence in a
    memory leak somewhere else - which is how a ranker becomes more certain the
    busier the cluster is.
    """
    return any(finding.subject == other.subject for other in supporting)


def _describe(subject: object) -> str | None:
    kind = getattr(subject, "kind", None)
    name = getattr(subject, "name", None)
    return f"{kind}/{name}" if kind and name else None


def _statement(category: RootCauseCategory, supporting: list[Finding], subject: object) -> str:
    """One sentence a human can act on.

    Templated rather than generated. No model is consulted here: the claim is
    entirely determined by which signal fired on which subject, and asking a
    model to phrase it would put a paraphrase between the evidence and the
    reader.
    """
    where = _describe(subject) or "this system"
    return f"{category.value.replace('_', ' ')} on {where}, from {len(supporting)} signal(s)"


def leading(hypotheses: list[RootCauseHypothesis]) -> RootCauseHypothesis | None:
    """The hypothesis a Verdict's confidence is about, or `None`.

    `None` when nothing was proposed, and `None` is what keeps
    `Verdict.confidence` at 0.0 honestly - it is defined as confidence in a
    leading hypothesis, so with none there is nothing to be confident about.

    A tie is not a leader. Two hypotheses at equal confidence are exactly the
    case where picking one is the ranker inventing a judgement it did not make.
    """
    if not hypotheses:
        return None
    best, *rest = hypotheses
    if rest and rest[0].confidence == best.confidence:
        return None
    return best
