"""Read-only Alertmanager tools: what is firing, and what is silenced.

Phase 1 uses the *receiver* in `api/routers/alerts.py` as the trigger path -
Alertmanager pushes, Pantheon does not poll. These tools exist for an agent that
wants to ask a follow-up question, and they are read-only for the same reason
the Prometheus ones are: Alertmanager can create and expire silences, which is a
state change and belongs behind the approval path.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

READ_PATHS = ("/api/v2/alerts", "/api/v2/silences")

#: The one path that changes Alertmanager's state. Separate from READ_PATHS on
#: purpose: a single allowlist would make adding a write as easy as adding a
#: read, and the whole point is that the two are not the same act.
WRITE_PATHS = ("/api/v2/silences",)

#: The longest a silence may be asked for. A silence is a decision to stop
#: paging, and one that outlives the incident is how an outage goes unnoticed
#: for a weekend. Capped here rather than trusted from the caller, because the
#: caller is an agent proposing an Action.
MAX_SILENCE_HOURS = 24
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


async def create_silence(arguments: dict[str, Any]) -> Any:
    """Silence matching alerts for a bounded period. **Mutating.**

    The first write tool in this repository. It is reachable only through
    `core/guardrails/executor.py`: no agent manifest may declare it, and
    `tests/unit/test_write_path.py` fails the build if one does.

    Alertmanager itself has no undo beyond expiring the silence, which is why
    `Action.rollback` is required for anything wider than one workload and why
    the duration is capped here - an unbounded silence is a decision nobody
    revisits.
    """
    matchers = arguments.get("matchers")
    if not matchers:
        raise ToolError(
            "create_silence needs `matchers`. A silence with no matchers silences "
            "EVERYTHING, and Alertmanager will accept it."
        )

    hours = float(arguments.get("hours", 1))
    if not 0 < hours <= MAX_SILENCE_HOURS:
        raise ToolError(
            f"hours={hours} is outside 0 to {MAX_SILENCE_HOURS}. A silence that "
            "outlives the incident is how an outage goes unnoticed for a weekend."
        )

    created_by = str(arguments.get("created_by") or "").strip()
    comment = str(arguments.get("comment") or "").strip()
    if not created_by or not comment:
        raise ToolError(
            "create_silence needs `created_by` and `comment`. An unattributed "
            "silence with no reason is one nobody can decide whether to keep."
        )

    starts = datetime.now(tz=UTC)
    body = {
        "matchers": matchers,
        "startsAt": starts.isoformat(),
        "endsAt": (starts + timedelta(hours=hours)).isoformat(),
        "createdBy": created_by,
        "comment": comment,
    }
    return await _post("/api/v2/silences", body)


async def _post(path: str, body: dict[str, Any]) -> Any:
    """One write against Alertmanager, against its own allowlist."""
    if path not in WRITE_PATHS:
        raise ToolError(f"{path!r} is not one of {list(WRITE_PATHS)}")

    base = get_settings().alertmanager.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(f"{base}{path}", json=body)
    except httpx.HTTPError as error:
        raise ToolError(f"alertmanager at {base} is unreachable: {error}") from error

    if response.status_code >= 400:
        raise ToolError(f"alertmanager returned {response.status_code}: {response.text[:200]}")
    return response.json()


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
    server.register(
        Tool(
            name="alertmanager.create_silence",
            description="Silence matching alerts for a bounded period.",
            schema={
                "type": "object",
                "properties": {
                    "matchers": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Alertmanager matchers. Required - see the handler.",
                    },
                    "hours": {"type": "number", "description": f"Up to {MAX_SILENCE_HOURS}."},
                    "created_by": {"type": "string"},
                    "comment": {"type": "string", "description": "Why. Never a credential."},
                },
                "required": ["matchers", "created_by", "comment"],
            },
            handler=create_silence,
            # The field, not a verb in the name. `tests/unit/test_write_path.py`
            # reads THIS to decide what an agent may not declare, so a tool that
            # writes and forgets the flag is reachable from an agent.
            mutating=True,
        )
    )
    return server
