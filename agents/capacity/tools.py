"""Connector tools Moira is allowed to call, and the adapters that shape them.

One tool. The manifest used to declare `kubernetes.list` and `kubernetes.top`
beside `prometheus.query_range`, and those two exist in no language - the Go
connector's read-only tools are scaffolding. `test_every_implemented_agent_can_
reach_the_tools_it_declares` refuses a dispatchable agent whose manifest names a
tool nothing implements, for the reason its docstring gives: the agent would
plan, dispatch, and fail at call time.

So the manifest declares what can be called today. When the Kubernetes tools
exist they return to the manifest and Moira gains a memory limit to project
against - see `agent.py` for what that unblocks.

Phase: 5 - Proactive Flow
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
            "step": kwargs.get("step", "60s"),
        }
    )


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS = {
    "prometheus.query_range": _range,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has."""
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
