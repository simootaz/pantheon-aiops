"""Builds the toolset an agent is allowed, from its manifest.

The manifest is the allowlist (see `agents/_base/tool_binding.py`), and this is
where declared names meet actual connector implementations. A tool an agent
declares but no connector provides stays unbound: `BoundTools.call` then raises
`ToolNotBound`, which is a different failure from `ToolNotDeclared` and reads
differently in the Finding - "the connector is not running" rather than "you may
not".

Only Prometheus is wired. Loki, Kubernetes, GitLab and the rest exist as
manifest entries and nothing else, so an agent declaring them constructs fine
and degrades honestly on first use - which is the behaviour `bind_tools` was
written to allow.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.prometheus import tools as prometheus
from core.contracts.manifest import AgentManifest


def _range(**kwargs: Any) -> Awaitable[Any]:
    return prometheus.query_range(
        {
            "query": kwargs["query"],
            "start": kwargs["start"],
            "end": kwargs["end"],
            "step": kwargs.get("step", "15s"),
        }
    )


def _instant(**kwargs: Any) -> Awaitable[Any]:
    return prometheus.query_instant({"query": kwargs["query"], "time": kwargs.get("time")})


def _series(**kwargs: Any) -> Awaitable[Any]:
    return prometheus.series(
        {"match": kwargs.get("match"), "start": kwargs.get("start"), "end": kwargs.get("end")}
    )


#: Declared name to implementation. Adding a connector means adding a row here,
#: which is deliberate: a lookup that imported by convention would bind whatever
#: happened to be importable.
IMPLEMENTATIONS = {
    "prometheus.query_range": _range,
    "prometheus.query_instant": _instant,
    "prometheus.series": _series,
}


def for_manifest(manifest: AgentManifest) -> BoundTools:
    """The toolset for one agent: everything it declares that anything provides."""
    bound = BoundTools(
        declared=frozenset(manifest.tools),
        max_calls=manifest.budget.max_tool_calls,
    )
    for name in manifest.tools:
        implementation = IMPLEMENTATIONS.get(name)
        if implementation is not None:
            bound.register(name, implementation)
    return bound
