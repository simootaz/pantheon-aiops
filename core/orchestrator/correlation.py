"""Grouping Findings that describe one resource in one window.

WHAT THIS CLAIMS, AND WHAT IT REFUSES TO
------------------------------------------
It claims **co-occurrence**: these Findings are about the same resource, and
their windows overlap. That is a fact, checkable from the Findings themselves.

It does **not** claim they share a cause. "The memory anomaly caused the OOM"
and "the OOM caused the memory anomaly" are both consistent with co-occurrence,
and choosing between them is a root-cause judgement that nothing in this
repository makes. `simulator/scenarios/*.yaml` carries ground truth for exactly
that field, so an invented ordering would be scored as though it were reasoning.

The same boundary Argus draws: it detects, it does not diagnose. This groups, it
does not explain.

WHY THIS IS WORTH HAVING ANYWAY
---------------------------------
An incident produces several Findings and the reader has no way to tell which
describe one event. During `bad_deploy_5xx` Argus reports `error_ratio` and
`latency` crossing, and both are correct; Lethe reports a novel `request failed`
pattern. Three Findings, one event, and nothing said so.

Grouping is also the step a ranker would need first, so building it separately
means the ranking work does not have to invent it.

WHY THE SUBJECT MUST MATCH EXACTLY
------------------------------------
`ResourceRef` carries no parent link: a pod does not know its service. So
`pod/checkout-7f9` and `service/checkout` cannot be joined here without a
topology source, and the Kubernetes connector that would provide one is a Go
stub.

Rather than guess a relationship from a name prefix - which works until a pod is
named after something else - the match is exact and the limitation is stated.
Lethe attributes to the narrowest resource its occurrences share, so when both
agents saw one pod they name the same one, and the join works.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from core.contracts.evidence import ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity

_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/zeus/correlation")

#: Evidence carried onto the correlation, per member. Capped so a correlation
#: over twenty Findings does not become a copy of the investigation - the
#: members are named in `related`, and that is where the detail lives.
EVIDENCE_PER_MEMBER = 1


def _key(subject: ResourceRef | None) -> tuple[str, str, str, str] | None:
    """The identity two Findings must share. `None` for an unattributed one.

    Unattributed Findings are excluded rather than grouped together. "Neither of
    these names a resource" is not something they have in common - it is a gap
    in both, and grouping on it would correlate every unattributed Finding in
    the run with every other.
    """
    if subject is None:
        return None
    return (subject.kind, subject.name, subject.namespace or "", subject.cluster or "")


def _overlaps(left: Finding, right: Finding) -> bool:
    """Whether two Findings describe overlapping periods.

    A Finding with no window is treated as overlapping anything. It was produced
    during this run, and refusing to group it would silently drop a whole agent
    from correlation the day one stops setting the field - which reads as "these
    never co-occur" rather than as a missing value.
    """
    if left.window_start is None or left.window_end is None:
        return True
    if right.window_start is None or right.window_end is None:
        return True
    return left.window_start <= right.window_end and right.window_start <= left.window_end


def correlate(findings: list[Finding]) -> list[Finding]:
    """One CORRELATION Finding per resource that several Findings describe.

    Returns `[]` when nothing co-occurs, which is a result rather than a
    failure - an investigation where each Finding stands alone is a legitimate
    outcome and must not be dressed up as one where they connect.

    DEGRADED Findings are excluded. They report that an agent could not look,
    so grouping one with a real observation would assert that a failure to
    measure co-occurred with the thing it failed to measure.
    """
    grouped: dict[tuple[str, str, str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        if finding.kind is FindingKind.DEGRADED:
            continue
        key = _key(finding.subject)
        if key is not None:
            grouped[key].append(finding)

    correlations: list[Finding] = []
    for key, members in sorted(grouped.items()):
        # A member is kept when it overlaps some OTHER member. Overlap is
        # symmetric, so this set is never size one: either nothing overlaps and
        # it is empty, or at least two do.
        #
        # That is why there is no separate "a group needs two" check. There was
        # one, and it could not fail - removing it and asserting the same rule
        # here leaves one expression of it that a plant can actually break.
        overlapping = [
            member
            for member in members
            if any(_overlaps(member, other) for other in members if other.id != member.id)
        ]
        if not overlapping:
            continue
        correlations.append(_correlation(key, overlapping))

    return correlations


def _correlation(key: tuple[str, str, str, str], members: list[Finding]) -> Finding:
    """One group, rendered as a Finding that names what it does not know."""
    kind, name, namespace, cluster = key
    subject = ResourceRef(
        kind=kind, name=name, namespace=namespace or None, cluster=cluster or None
    )
    agents = sorted({member.agent for member in members})

    evidence = [item for member in members for item in member.evidence[:EVIDENCE_PER_MEMBER]]

    starts = [m.window_start for m in members if m.window_start is not None]
    ends = [m.window_end for m in members if m.window_end is not None]

    return Finding(
        # Deterministic in the members, so re-running an investigation produces
        # the same correlation id rather than a new one each attempt.
        id=uuid5(_NAMESPACE, ":".join([*key, *sorted(str(m.id) for m in members)])),
        agent="zeus",
        kind=FindingKind.CORRELATION,
        title=f"{len(members)} findings describe {kind} {name} in the same window",
        # The same severity as every detection, for the same reason: ranking
        # means knowing which of these matters most, and that is the judgement
        # this explicitly does not make.
        severity=Severity.MEDIUM,
        # Co-occurrence is checkable from the Findings themselves - they either
        # name the same resource or they do not. The certainty is about THAT,
        # not about a shared cause, and the tag below says so.
        confidence=1.0,
        detected_at=datetime.now(tz=UTC),
        window_start=min(starts) if starts else None,
        window_end=max(ends) if ends else None,
        subject=subject,
        evidence=evidence,
        related=[member.id for member in members],
        rationale=(
            f"{', '.join(agents)} each reported on {kind} {name} within one window. "
            "That they co-occur is a fact; that one caused another is not claimed - "
            "nothing here ranks candidate causes."
        ),
        tags=[
            "correlation",
            f"members:{len(members)}",
            *[f"agent:{agent}" for agent in agents],
            "confidence:co-occurrence-is-not-causation",
        ],
    )
