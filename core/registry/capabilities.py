"""Which agents can satisfy a request, and in what order.

Zeus plans by naming a capability, never an agent: "someone establish a
baseline" rather than "ask Argus". That indirection is the whole point of the
manifest - it means adding an agent that declares `detect_metric_anomaly` makes
it eligible without editing the planner.

Matching is exact on the capability name. Deliberately not fuzzy: a planner that
half-matches `detect_metric_anomaly` against `detect_log_anomaly` dispatches to
the wrong specialist and the failure looks like a bad answer rather than a bad
route. Names are a closed vocabulary declared in manifests, so exactness costs
nothing and ambiguity costs a wrong diagnosis.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from core.contracts.manifest import AgentManifest
from core.registry.loader import load_all


class NoCapableAgent(LookupError):
    """Nothing declares the capability a plan step asked for."""


def capabilities() -> dict[str, list[str]]:
    """Capability name -> the codenames that declare it, sorted."""
    index: dict[str, list[str]] = {}
    for manifest in load_all().values():
        for capability in manifest.capabilities:
            index.setdefault(capability.name, []).append(manifest.codename)
    return {name: sorted(codenames) for name, codenames in sorted(index.items())}


def agents_for(capability: str) -> list[AgentManifest]:
    """Every agent that declares `capability`, cheapest budget first.

    Ranking by budget is a placeholder with a real justification: when two
    agents can do the same job, the one that asked for less is the one to try
    first. Phase 2 replaces this with scoring on past accuracy, which is the
    ranking that actually matters and needs history that does not exist yet.
    """
    matched = [
        manifest
        for manifest in load_all().values()
        if any(declared.name == capability for declared in manifest.capabilities)
    ]
    if not matched:
        raise NoCapableAgent(
            f"no agent declares {capability!r}. Declared capabilities: {sorted(capabilities())}"
        )
    return sorted(matched, key=lambda m: (m.budget.max_tool_calls, m.codename))


def best_for(capability: str) -> AgentManifest:
    """The single agent to dispatch for a capability."""
    return agents_for(capability)[0]


def declares(codename: str, capability: str) -> bool:
    """Whether one specific agent claims one specific capability."""
    manifests = load_all()
    if codename not in manifests:
        return False
    return any(declared.name == capability for declared in manifests[codename].capabilities)
