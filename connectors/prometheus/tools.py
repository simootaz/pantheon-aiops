"""The three read-only Prometheus tools Argus declares, and nothing else.

The tool names here are exactly the strings in `agents/anomaly/manifest.yaml`:
`prometheus.query_range`, `prometheus.query_instant`, `prometheus.series`. That
is not a coincidence to be maintained by hand - `tests/unit/test_connectors.py`
asserts the two sets match, in both directions, so a tool nobody declares and a
declaration nothing implements are both build failures.

READ-ONLY
---------
Every tool here reads. Prometheus does expose write and admin endpoints -
`/api/v1/admin/tsdb/delete_series` among them - and none is reachable from
here. `mutating=False` on all three is asserted rather than assumed, because the
moment a mutating tool exists it needs the approval path and the difference
between "we did not add one" and "we cannot add one without noticing" is the
whole point.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from typing import Any

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

#: Prometheus paths this connector may reach. An allowlist rather than a
#: denylist: a new Prometheus release adding a destructive endpoint must not
#: silently become reachable.
READ_PATHS = ("/api/v1/query", "/api/v1/query_range", "/api/v1/series")

TIMEOUT_SECONDS = 30.0


async def _get(path: str, params: dict[str, Any]) -> Any:
    """One read against Prometheus, with the failure surfaced rather than hidden."""
    if path not in READ_PATHS:
        raise ToolError(
            f"{path!r} is not one of this connector's read paths {list(READ_PATHS)}. "
            "Prometheus write and admin endpoints are deliberately unreachable."
        )

    base = get_settings().prometheus.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}{path}", params=params)
    except httpx.HTTPError as error:
        raise ToolError(f"prometheus at {base} is unreachable: {error}") from error

    if response.status_code >= 400:
        raise ToolError(f"prometheus returned {response.status_code}: {response.text[:200]}")

    body = response.json()
    if body.get("status") != "success":
        raise ToolError(f"prometheus rejected the query: {body.get('error', body)}")
    return body["data"]


async def query_instant(arguments: dict[str, Any]) -> Any:
    """Evaluate a PromQL expression at a single point in time."""
    query = arguments.get("query")
    if not query:
        raise ToolError("query_instant needs a `query`")
    params: dict[str, Any] = {"query": query}
    if arguments.get("time"):
        params["time"] = arguments["time"]
    return await _get("/api/v1/query", params)


async def query_range(arguments: dict[str, Any]) -> Any:
    """Evaluate a PromQL expression over a window.

    This is the one Argus leans on: a baseline is a shape over time, and an
    instant query cannot show one.
    """
    for required in ("query", "start", "end"):
        if not arguments.get(required):
            raise ToolError(f"query_range needs a `{required}`")
    return await _get(
        "/api/v1/query_range",
        {
            "query": arguments["query"],
            "start": arguments["start"],
            "end": arguments["end"],
            "step": arguments.get("step", "15s"),
        },
    )


async def series(arguments: dict[str, Any]) -> Any:
    """List the series matching a selector, for discovering what exists."""
    matches = arguments.get("match")
    if not matches:
        raise ToolError("series needs a `match` selector")
    params: dict[str, Any] = {"match[]": matches}
    for optional in ("start", "end"):
        if arguments.get(optional):
            params[optional] = arguments[optional]
    return await _get("/api/v1/series", params)


_QUERY = {"type": "string", "description": "A PromQL expression."}
_TIMESTAMP = {"type": "string", "description": "RFC3339 or a unix timestamp."}


def build_server() -> BaseMCPServer:
    """The Prometheus connector, with exactly the tools Argus declares."""
    server = BaseMCPServer(name="prometheus")

    server.register(
        Tool(
            name="prometheus.query_instant",
            description="Evaluate a PromQL expression at a single instant.",
            schema={
                "type": "object",
                "properties": {"query": _QUERY, "time": _TIMESTAMP},
                "required": ["query"],
            },
            handler=query_instant,
        )
    )
    server.register(
        Tool(
            name="prometheus.query_range",
            description="Evaluate a PromQL expression over a time window.",
            schema={
                "type": "object",
                "properties": {
                    "query": _QUERY,
                    "start": _TIMESTAMP,
                    "end": _TIMESTAMP,
                    "step": {"type": "string", "description": "Resolution, e.g. '15s'."},
                },
                "required": ["query", "start", "end"],
            },
            handler=query_range,
        )
    )
    server.register(
        Tool(
            name="prometheus.series",
            description="List series matching one or more selectors.",
            schema={
                "type": "object",
                "properties": {
                    "match": {"type": "array", "items": {"type": "string"}},
                    "start": _TIMESTAMP,
                    "end": _TIMESTAMP,
                },
                "required": ["match"],
            },
            handler=series,
        )
    )
    return server
