"""Agent introspection endpoints backed by core.registry.

WHAT A MANIFEST SAYS, AND WHAT IT DOES NOT
-------------------------------------------
Ten manifests load and validate. One agent has an implementation. A listing
that showed only the manifests would tell a reader that Pantheon has ten working
agents, which is the single most misleading thing this API could say - so
`implemented` is on every row, and it comes from the dispatcher's registry
rather than from the manifest.

That distinction is the same one `PlanStep.status` draws between COMPLETE and
SKIPPED: declaring an intention and doing the thing are different facts, and an
interface that collapses them makes a stub indistinguishable from an agent.

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
        implemented=manifest.codename in dispatcher.AGENTS,
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
