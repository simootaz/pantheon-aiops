"""Connector tools Argus is allowed to call, and the adapters that shape them.

`BaseAgent.run` constructs the toolset from the manifest and hands it to
`bind_tools`, which is where implementations are attached. That ownership matters
and cost a live gate to learn: an orchestrator that built its own toolset and set
`ctx.tools` had it silently replaced by the runtime, and every call came back
`ToolNotBound`. The agent's own `bind_tools` is the only place that works.

The adapters exist because the connector takes one `arguments` dict and callers
pass keywords. Doing that translation here keeps the connector's MCP-shaped
signature intact and keeps the keyword call sites readable.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.prometheus import tools as prometheus


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


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS = {
    "prometheus.query_range": _range,
    "prometheus.query_instant": _instant,
    "prometheus.series": _series,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has.

    Silent about the rest on purpose: a declared tool with no implementation
    stays unbound and raises `ToolNotBound` at call time, which reads as "the
    connector is not running" rather than "you may not" - a distinction
    `tool_binding.py` exists to preserve.
    """
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
