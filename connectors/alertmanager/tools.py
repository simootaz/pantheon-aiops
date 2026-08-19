"""Read-only Alertmanager tools: what is firing, and what is silenced.

Phase 1 uses the *receiver* in `api/routers/alerts.py` as the trigger path -
Alertmanager pushes, Pantheon does not poll. These tools exist for an agent that
wants to ask a follow-up question, and they are read-only for the same reason
the Prometheus ones are: Alertmanager can create and expire silences, which is a
state change and belongs behind the approval path.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from typing import Any

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

READ_PATHS = ("/api/v2/alerts", "/api/v2/silences")
TIMEOUT_SECONDS = 15.0


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    if path not in READ_PATHS:
        raise ToolError(f"{path!r} is not one of {list(READ_PATHS)}")

    base = get_settings().alertmanager.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}{path}", params=params or {})
    except httpx.HTTPError as error:
        raise ToolError(f"alertmanager at {base} is unreachable: {error}") from error

    if response.status_code >= 400:
        raise ToolError(f"alertmanager returned {response.status_code}: {response.text[:200]}")
    return response.json()


async def list_alerts(arguments: dict[str, Any]) -> Any:
    """Alerts Alertmanager currently knows about."""
    params: dict[str, Any] = {}
    if arguments.get("filter"):
        params["filter"] = arguments["filter"]
    if "silenced" in arguments:
        params["silenced"] = str(bool(arguments["silenced"])).lower()
    return await _get("/api/v2/alerts", params)


async def list_silences(arguments: dict[str, Any]) -> Any:
    """Active silences, so an agent can tell quiet from healthy."""
    params = {"filter": arguments["filter"]} if arguments.get("filter") else {}
    return await _get("/api/v2/silences", params)


def build_server() -> BaseMCPServer:
    server = BaseMCPServer(name="alertmanager")
    server.register(
        Tool(
            name="alertmanager.list_alerts",
            description="List alerts Alertmanager currently holds.",
            schema={
                "type": "object",
                "properties": {
                    "filter": {"type": "array", "items": {"type": "string"}},
                    "silenced": {"type": "boolean"},
                },
            },
            handler=list_alerts,
        )
    )
    server.register(
        Tool(
            name="alertmanager.list_silences",
            description="List active silences.",
            schema={
                "type": "object",
                "properties": {"filter": {"type": "array", "items": {"type": "string"}}},
            },
            handler=list_silences,
        )
    )
    return server
