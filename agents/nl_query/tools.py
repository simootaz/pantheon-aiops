"""Connector tools Hermes is allowed to call, and the adapters that shape them.

Two connectors, one adapter each. Same split as `agents/anomaly/tools.py` and
`agents/log_clustering/tools.py`: the connector takes one `arguments` dict and
callers pass keywords.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.loki import tools as loki
from connectors.prometheus import tools as prometheus


def _instant(**kwargs: Any) -> Awaitable[Any]:
    return prometheus.query_instant({"query": kwargs["query"], "time": kwargs.get("time")})


def _logs(**kwargs: Any) -> Awaitable[Any]:
    return loki.query_range(
        {
            "query": kwargs["query"],
            "start": kwargs["start"],
            "end": kwargs["end"],
            "limit": kwargs.get("limit"),
            "direction": kwargs.get("direction", "backward"),
        }
    )


#: Declared name to implementation. `register` refuses a name the manifest does
#: not declare, so this can only fill the allowlist - never widen it.
IMPLEMENTATIONS = {
    "prometheus.query_instant": _instant,
    "loki.query_range": _logs,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has."""
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
