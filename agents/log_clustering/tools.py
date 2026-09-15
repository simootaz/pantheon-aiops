"""Connector tools Lethe is allowed to call, and the adapters that shape them.

`BaseAgent.run` constructs the toolset from the manifest and hands it to
`bind_tools`, which is where implementations are attached. That ownership cost a
live gate to learn on Argus: an orchestrator that built its own toolset and set
`ctx.tools` had it silently replaced by the runtime, and every call came back
`ToolNotBound`.

The adapters exist because the connector takes one `arguments` dict and callers
pass keywords - the same split as `agents/anomaly/tools.py`, for the same reason.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.loki import tools as loki


def _range(**kwargs: Any) -> Awaitable[Any]:
    return loki.query_range(
        {
            "query": kwargs["query"],
            "start": kwargs["start"],
            "end": kwargs["end"],
            "limit": kwargs.get("limit"),
            "direction": kwargs.get("direction", "backward"),
        }
    )


def _labels(**kwargs: Any) -> Awaitable[Any]:
    return loki.labels(
        {"name": kwargs.get("name"), "start": kwargs.get("start"), "end": kwargs.get("end")}
    )


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS = {
    "loki.query_range": _range,
    "loki.labels": _labels,
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
