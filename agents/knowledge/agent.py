"""Mnemosyne - has this happened before, and what did we conclude.

WHAT THIS DOES, AND WHAT IT DOES NOT
--------------------------------------
It asks the store for prior investigations of the same alert on the same
subject and reports what they concluded. That is a keyed lookup on the
trigger's own labels - `core/memory/recall.py` says which - and not a search
for anything "similar", which would need a notion of similarity nobody here
has measured.

One Finding, when there are priors. None when there are not: "first time this
has fired here" is a fact, and it is the fact the step's clean completion
already states. A Finding saying "no history" would be an agent that found
nothing reporting that it found nothing, in a list meant for things found.

HISTORY IS FOR THE PERSON, NOT THE RANKER
-------------------------------------------
What a prior verdict concluded says nothing about what is happening now. The
Finding's evidence is `PriorIncidentPayload` and nothing else, and
`hypotheses.rank` excludes such a Finding entirely - not merely from proposing
a cause, but from corroborating one, because it shares the subject and would
otherwise raise confidence in whatever the ranker already leaned towards.

WHAT IT DOES NOT SEARCH
-------------------------
Runbooks. The manifest used to declare `find_runbook`; nothing stores a
runbook, and a capability nothing can perform reads as one that works. When
something does, it returns.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agents._base.base_agent import AgentContext, BaseAgent
from agents.knowledge.tools import attach
from core.contracts.evidence import Evidence, EvidenceSource, PriorIncidentPayload, ResourceRef
from core.contracts.finding import Finding, FindingKind, Severity
from core.memory.recall import TOOL_NAME, alert_key

_EVIDENCE_NAMESPACE = uuid5(NAMESPACE_URL, "https://pantheon.local/mnemosyne/evidence")

#: Priors carried on the Finding. Newest first; the rest are counted in the
#: title so a reader knows there are more than were listed.
MAX_LISTED = 5

#: Constant, for the reason Argus's is. A fifth recurrence is not more severe
#: than a second in any way this agent can measure; the count is in the title.
RECALL_SEVERITY = Severity.INFO


class Mnemosyne(BaseAgent):
    """Prior investigations of this alert on this subject, from the store."""

    domain = "knowledge"

    def bind_tools(self, tools: Any) -> None:
        attach(tools)

    async def investigate(self, ctx: AgentContext) -> list[Finding]:
        """The priors, as one Finding, or nothing when there are none."""
        key = alert_key(ctx.trigger)
        if key is None:
            # Not an alert, or an alert with no name. There is nothing to match
            # a prior against, and matching on nothing makes every run a prior.
            return []

        priors: list[dict[str, Any]] = await ctx.tools.call(TOOL_NAME)
        if not priors:
            return []

        subject = _subject_of(key)
        listed = priors[:MAX_LISTED]
        latest = listed[0]

        return [
            Finding(
                id=uuid5(_EVIDENCE_NAMESPACE, f"finding:{ctx.investigation_id}"),
                agent=self.codename,
                kind=FindingKind.OBSERVATION,
                title=_title(key, priors, latest),
                severity=RECALL_SEVERITY,
                # Read off the store, not inferred. The uncertainty is whether
                # the past applies to the present, and this agent does not
                # make that claim - see the module docstring.
                confidence=1.0,
                detected_at=datetime.now(tz=UTC),
                window_start=ctx.window_start,
                window_end=ctx.window_end,
                subject=subject,
                evidence=[
                    Evidence(
                        id=uuid5(
                            _EVIDENCE_NAMESPACE,
                            f"{ctx.investigation_id}:{prior['investigation_id']}",
                        ),
                        source=EvidenceSource(
                            connector="memory", query=f"recall alertname={key['alertname']}"
                        ),
                        observed_at=datetime.fromisoformat(prior["created_at"]),
                        summary=_summary(prior),
                        subject=subject,
                        payload=PriorIncidentPayload(
                            investigation_id=UUID(prior["investigation_id"]),
                            created_at=datetime.fromisoformat(prior["created_at"]),
                            state=prior["state"],
                            category=prior.get("category"),
                            confidence=prior.get("confidence"),
                            partial=bool(prior.get("partial", False)),
                        ),
                    )
                    for prior in listed
                ],
                tags=["history", f"recurrences:{len(priors)}"],
            )
        ]


def _subject_of(key: dict[str, str]) -> ResourceRef | None:
    """The most specific subject label the alert carries, as a ResourceRef."""
    for kind in ("pod", "service", "node", "instance"):
        if kind in key:
            return ResourceRef(kind=kind, name=key[kind], namespace=key.get("namespace"))
    return None


def _title(key: dict[str, str], priors: list[dict[str, Any]], latest: dict[str, Any]) -> str:
    where = ", ".join(f"{k}={v}" for k, v in key.items() if k != "alertname")
    times = "once before" if len(priors) == 1 else f"{len(priors)} times before"
    concluded = (
        f"; the last run concluded {latest['category']} at {latest['confidence']:.2f}"
        if latest.get("category")
        else "; the last run reached no conclusion"
    )
    return f"{key['alertname']} has fired {times} on {where or 'this subject'}{concluded}"


def _summary(prior: dict[str, Any]) -> str:
    when = prior["created_at"][:19].replace("T", " ")
    outcome = (
        f"{prior['category']} at {prior['confidence']:.2f}"
        if prior.get("category")
        else "no leading hypothesis"
    )
    partial = " (partial)" if prior.get("partial") else ""
    return f"{when}: {prior['state']}, {outcome}{partial}"
