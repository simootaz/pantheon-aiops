"""Agent introspection endpoints backed by core.registry.

WHAT A MANIFEST SAYS, AND WHAT IT DOES NOT
-------------------------------------------
Ten manifests load and validate. Six have code behind them, and five of those
can be reached by a trigger. A listing that showed only the manifests would tell
a reader that Pantheon has ten working agents, which is the single most
misleading thing this API could say - so `implemented` and `dispatchable` are
both on every row, and both come from the dispatcher's registry rather than from
the manifest.

That distinction is the same one `PlanStep.status` draws between COMPLETE and
SKIPPED: declaring an intention and doing the thing are different facts, and an
interface that collapses them makes a stub indistinguishable from an agent.

THE SECOND FIELD EXISTS BECAUSE THE FIRST HAD STOPPED BEING TRUE
-----------------------------------------------------------------
`implemented` was read from the dispatchable registry, so Themis - written,
tested, and unreachable because nothing schedules anything yet - was reported
the same way as Clio, which is a manifest and nothing else. The field's name had
stopped naming what it measured. Splitting it is the fix; narrowing the claim in
the docstring would have been the other one.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.schemas.common import AgentSummary
from core.contracts.manifest import AgentManifest
from core.orchestrator import dispatcher
from core.registry import loader

router = APIRouter(prefix="/agents", tags=["agents"])


def _summarise(manifest: AgentManifest) -> AgentSummary:
    return AgentSummary(
        codename=manifest.codename,
        domain=manifest.domain,
        description=manifest.description,
        capabilities=[capability.name for capability in manifest.capabilities],
        tools=list(manifest.tools),
        implemented=manifest.codename in dispatcher.IMPLEMENTATIONS,
        # AGENTS, not IMPLEMENTATIONS. The narrower set: an agent is
        # dispatchable only once some trigger produces a plan that names it.
        dispatchable=manifest.codename in dispatcher.AGENTS,
    )


@router.get("", response_model=list[AgentSummary], summary="Every agent on the roster")
async def list_agents() -> list[AgentSummary]:
    """The roster, in codename order, each row saying whether it can actually run."""
    return [_summarise(manifest) for _, manifest in sorted(loader.load_all().items())]


@router.get(
    "/{codename}",
    response_model=AgentManifest,
    summary="One agent's manifest, whole",
)
async def get_agent(codename: str) -> AgentManifest:
    """The manifest verbatim, including the tool allowlist and the budget.

    Whole rather than summarised: the tool allowlist and the budget are what
    someone comes here to check, and a summary that dropped either would have to
    be re-derived from the file it was summarising.
    """
    try:
        return loader.for_codename(codename)
    except loader.ManifestError as unknown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no agent {codename!r}. Roster: {sorted(loader.load_all())}",
        ) from unknown
