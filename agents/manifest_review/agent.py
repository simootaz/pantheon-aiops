"""Aegis - reports what a manifest change takes away, before it ships.

WHAT THIS DOES, AND WHAT IT DOES NOT
------------------------------------
It reports **safety properties the change removes**, and how far the changed
object can reach. That is the whole of it.

It does not decide whether the change is wrong. Deleting a readiness probe is
sometimes correct - a batch worker that serves no traffic does not need one -
and Aegis has no way to know which case it is looking at. The Finding says what
was taken away and what that exposes; whether that is acceptable is the review,
and the reviewer is a person.

There is no risk score. A number would have to be tuned against some corpus of
changes, and every reader would treat it as calibrated when it was fitted -
`docs/lethe-predictions/` records what that costs. Reach is categorical and
comes from the Kubernetes object model; replica counts are reported as read.

THE DIFF IS SUPPLIED, NOT FETCHED
-----------------------------------
Aegis reads `before` and `after` manifests off `ctx.params`. It does not fetch
them: `connectors/gitlab` and `connectors/github` are Phase 4 stubs, so there is
nothing to fetch from.

That is stated rather than worked around. An agent that quietly reviewed only
the `after` state because it could not get the `before` would report on the
workload instead of the change, which is precisely the failure `diff.py` exists
to avoid - and it would look like a working review.

WHAT IT CANNOT SEE
--------------------
* **How many pods a change actually reaches.** `replicas` is in the manifest; a
  DaemonSet's pod count is the node count, and a ConfigMap's consumers are
  whoever mounts it. Reach is a bound, not a count.
* **Anything outside the manifests it was given.** A PodDisruptionBudget
  deleted in another file protects a Deployment reviewed here, and Aegis sees
  one file at a time unless both are passed together.
* **Whether the change is what the author intended.** A removed limit and a
  deliberate removal of a limit are the same diff.

No LLM is involved. `Finding.rationale` is optional, so a templated title and
real Evidence are a complete claim - the same choice as Lethe and Argus.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agents._base.base_agent import AgentContext, AgentDegraded, BaseAgent
from agents.manifest_review.diff import Reach, Review, review
from core.contracts.evidence import (
    Evidence,
    EvidenceSource,
    ManifestDiffPayload,
    ResourceRef,
)
from core.contracts.finding import Finding, FindingKind, Severity

#: Namespace for deterministic evidence ids, so the same change carries the same
#: id on every attempt - the reason `BaseAgent.finding_id` exists.
_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/aegis/evidence")

#: The two sides of a change, joined. Named because the alternative is an
#: escape inside an f-string, which older Python parsers reject outright.
_SIDES = "\n"

#: Severity by reach, and by nothing else.
#:
#: Reach is categorical and comes from the Kubernetes object model rather than
#: from a threshold fitted to a corpus: a ClusterRoleBinding reaches every
#: namespace whatever anybody thinks about it, and a Deployment reaches its own
#: pods. A weighting over which protections matter more would be an opinion
#: dressed as a measurement.
SEVERITY_BY_REACH = {
    Reach.CLUSTER: Severity.HIGH,
    Reach.NAMESPACE: Severity.MEDIUM,
    Reach.WORKLOAD: Severity.MEDIUM,
}


class Aegis(BaseAgent):
    """The change side of review. Reports what a manifest change removes."""

    domain = "manifest_review"

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """Report every safety property the reviewed change takes away.

        Returns `[]` when the change removes nothing - a result, not a failure.
        Most changes are an image tag.

        Raises `AgentDegraded` when there is nothing to review, or when only
        one side of the change was supplied: reviewing an `after` with no
        `before` reports on the workload rather than on the change, and would
        look like a working review while being a different question.
        """
        changes = self._changes(ctx)
        findings: list[Finding] = []

        for index, (before, after) in enumerate(changes):
            assessment = review(before, after)
            if assessment.clean:
                continue
            findings.append(self._finding(ctx, assessment, index, before, after))

        return findings

    def _changes(
        self, ctx: AgentContext
    ) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
        """The before/after pairs to review, from `ctx.params`.

        Two shapes are accepted: `changes`, a list of `{before, after}`, and a
        bare `before`/`after` pair for the single-object case. Anything else is
        a caller error and is refused rather than reviewed as empty - an agent
        that returned no findings for a malformed input would be indistinguishable
        from one that reviewed a safe change.
        """
        raw = ctx.params.get("changes")
        if raw is None and ("before" in ctx.params or "after" in ctx.params):
            raw = [{"before": ctx.params.get("before"), "after": ctx.params.get("after")}]

        if not raw:
            raise AgentDegraded(
                "no manifests were supplied to review. Aegis reads `before` and "
                "`after` off ctx.params and does not fetch them - the gitlab and "
                "github connectors are Phase 4 stubs, so there is nothing to fetch "
                "from. A review with no diff is not an empty result.",
                partial=[],
                retryable=False,
            )

        if not isinstance(raw, list):
            raise AgentDegraded(
                f"`changes` is a {type(raw).__name__}, not a list of "
                "{before, after} pairs. Reviewing it as empty would report a clean "
                "change for input nobody could parse.",
                partial=[],
                retryable=False,
            )

        pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise AgentDegraded(
                    f"a change entry is a {type(entry).__name__}, not a mapping with "
                    "`before` and `after`.",
                    partial=[],
                    retryable=False,
                )
            before, after = entry.get("before"), entry.get("after")
            if before is None and after is None:
                raise AgentDegraded(
                    "a change entry has neither `before` nor `after`. An empty pair "
                    "reviews as clean, which is the wrong answer to a malformed input.",
                    partial=[],
                    retryable=False,
                )
            pairs.append((before, after))
        return pairs

    def _finding(
        self,
        ctx: AgentContext,
        assessment: Review,
        index: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> Finding:
        subject = ResourceRef(
            kind=assessment.kind.lower(),
            name=assessment.name,
            namespace=assessment.namespace,
        )
        removed = [protection.name for protection in assessment.removed]
        headline = (
            f"{assessment.kind} {assessment.name} is deleted"
            if assessment.deleted
            else f"{assessment.kind} {assessment.name} loses {_listed(removed)}"
        )

        finding = Finding(
            id=ctx.investigation_id,
            agent=self.codename,
            kind=FindingKind.RISK,
            title=f"{headline} ({assessment.reach.value} reach)",
            severity=SEVERITY_BY_REACH[assessment.reach],
            # Stated, not estimated. The removals are read off the manifests and
            # there is no inference between the diff and the claim - what would
            # be uncertain is whether the removal MATTERS, and Aegis does not
            # make that claim.
            confidence=1.0,
            detected_at=ctx.window_end,
            window_start=ctx.window_start,
            window_end=ctx.window_end,
            subject=subject,
            evidence=[
                Evidence(
                    id=uuid5(_EVIDENCE_NAMESPACE, f"{ctx.investigation_id}:{index}"),
                    source=EvidenceSource(connector="params", query="ctx.params.changes"),
                    observed_at=ctx.window_end,
                    summary=_summary(assessment),
                    subject=subject,
                    payload=ManifestDiffPayload(
                        target=subject,
                        diff=_rendered(before, after),
                        changed_fields=removed,
                    ),
                )
            ],
            tags=["manifest", assessment.reach.value],
        )
        return finding


def _listed(names: list[str]) -> str:
    """Names in a title, bounded. A title is one line somebody scans."""
    if len(names) <= 2:
        return " and ".join(names)
    return f"{names[0]}, {names[1]} and {len(names) - 2} more"


def _summary(assessment: Review) -> str:
    """One line a human reads without expanding the payload."""
    if assessment.deleted:
        return (
            f"{assessment.kind} {assessment.name} is removed entirely; it held "
            f"{len(assessment.removed)} declared protections"
        )
    exposures = "; ".join(
        f"{protection.name} - {protection.exposes}" for protection in assessment.removed
    )
    scale = ""
    if assessment.replicas_before != assessment.replicas_after:
        scale = f" Replicas {assessment.replicas_before} to {assessment.replicas_after}."
    return f"{exposures}.{scale}"


def _rendered(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    """A minimal record of the two sides.

    Not a unified diff. Producing one would mean re-serialising both manifests
    to text and diffing the text, which reports formatting changes as content -
    and the fields that actually changed are already on `changed_fields`.
    """
    sides = [
        f"{name}: {'absent' if manifest is None else 'present'}"
        for name, manifest in (("before", before), ("after", after))
    ]
    return _SIDES.join(sides)
