"""AgentManifest: the declarative capability descriptor every agent ships.

core.registry.loader reads one of these from each agents/<domain>/manifest.yaml
and matches them against plan steps.

Phase 1 will expand this: capability argument schemas and per-capability cost
hints.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from pydantic import Field

from core.contracts.base import ContractModel


class AgentCapability(ContractModel):
    """One thing an agent claims it can do."""

    name: str = Field(description="Stable identifier, e.g. 'detect_metric_anomaly'.")
    description: str


class AgentBudget(ContractModel):
    """Ceilings the dispatcher enforces for a single agent invocation."""

    max_tokens: int = Field(gt=0)
    max_seconds: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)


class AgentManifest(ContractModel):
    """Everything the registry needs to know about an agent without importing it."""

    codename: str = Field(description="Mythological name, e.g. 'argus'.")
    domain: str = Field(description="Folder under agents/, e.g. 'anomaly'.")
    description: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    tools: list[str] = Field(
        default_factory=list, description="Connector tools this agent may call."
    )
    budget: AgentBudget


# TODO: Phase 1 - add capability argument schemas and per-capability cost hints
