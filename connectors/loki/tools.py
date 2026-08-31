"""The two read-only Loki tools Lethe declares, and nothing else.

The names here are exactly the strings in `agents/log_clustering/manifest.yaml`:
`loki.query_range` and `loki.labels`. `tests/unit/test_connectors.py` asserts the
two sets match in both directions, so a tool nobody declares and a declaration
nothing implements are both build failures.

READ-ONLY
---------
Loki's write surface is real and destructive: `POST /loki/api/v1/push` ingests,
and the delete API removes log lines outright, permanently, for a tenant. None
of it is reachable from here. The path allowlist is the mechanism - a denylist
would have to know today about the endpoint added in the next release.

WHY THE ALLOWLIST HAS ONE TEMPLATE ENTRY
------------------------------------------
Label *values* live under a path segment - `/loki/api/v1/label/<name>/values` -
so an exact-match tuple cannot express it. Lethe needs values, not just names:
`cluster_logs` starts from a LogQL selector, and a list of label names with no
values cannot produce one.

Rather than loosen the allowlist to a prefix match, the label name is validated
against the character class Loki itself accepts, and the built path is then
checked against the same allowlist as every other. A prefix match would have
admitted a traversal out of the label segment; this does not, and the test in
tests/unit/test_connectors.py is what says so rather than this comment.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

#: Loki paths this connector may reach. Exact strings; the one placeholder is
#: substituted only through `_label_values_path`, which validates first.
READ_PATHS = (
    "/loki/api/v1/query_range",
    "/loki/api/v1/labels",
    "/loki/api/v1/label/<name>/values",
)

#: What Loki accepts as a label name. Used to build a path, so it is anchored:
#: an unanchored pattern matches a prefix of a hostile string and passes it on.
LABEL_NAME = re.compile(r"\A[a-zA-Z_][a-zA-Z0-9_]*\Z")

#: The concrete form of the one templated entry above, so a single allowlist
#: covers both the fixed paths and the parameterised one.
_VALUES_PATH = re.compile(r"\A/loki/api/v1/label/[^/]+/values\Z")

TIMEOUT_SECONDS = 30.0

#: Loki refuses a query_range asking for more than this many entries, and the
#: refusal arrives as a 400 that reads like a malformed query. Capped here so
#: the error names the cap instead.
MAX_LIMIT = 5000

#: Loki's own default is 100, which silently truncates a busy window - and a
#: truncated log window looks exactly like a quiet service.
DEFAULT_LIMIT = 1000

#: Passed as `empty` by a caller whose endpoint always sends `data`. Absence
#: there is a change in Loki, not a quiet window, so it is reported rather than
#: smoothed over into a plausible-looking result.
#:
#: The two behaviours are measured, not assumed - see tests/integration/
#: test_loki_connector.py, which asserts both against a real Loki.
REPORT_ABSENCE: Any = object()


def _label_values_path(name: str) -> str:
    """Build the label-values path, or refuse.

    Validation before substitution, not after. A name checked once it is already
    inside a URL is a name checked too late.
    """
    if not LABEL_NAME.match(name):
        raise ToolError(
            f"{name!r} is not a valid Loki label name. Expected letters, digits "
            "and underscore, not starting with a digit - it is substituted into "
            "a request path, so it is validated rather than escaped."
        )
    return f"/loki/api/v1/label/{name}/values"


def _allowed(path: str) -> bool:
    """Whether this connector may reach `path`.

    Pure, so the allowlist can be tested without opening a socket. The first
    version of that test made a real request to find out, which on a developer
    machine with the stack up passes for a reason CI cannot reproduce.
    """
    return path in READ_PATHS or bool(_VALUES_PATH.match(path))


async def _get(path: str, params: dict[str, Any] | None = None, *, empty: Any) -> Any:
    """One read against Loki, with the failure surfaced rather than hidden.

    `empty` is what this endpoint returns when Loki has nothing - see below. It
    is required rather than defaulted, because the right answer differs per
    endpoint and a default would be a guess made once and inherited everywhere.
    """
    if not _allowed(path):
        raise ToolError(
            f"{path!r} is not one of this connector's read paths {list(READ_PATHS)}. "
            "Loki's push and delete endpoints are deliberately unreachable."
        )

    base = get_settings().loki.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}{path}", params=params or {})
    except httpx.HTTPError as error:
        raise ToolError(f"loki at {base} is unreachable: {error}") from error

    if response.status_code >= 400:
        raise ToolError(f"loki returned {response.status_code}: {response.text[:200]}")

    body = response.json()
    if body.get("status") != "success":
        raise ToolError(f"loki rejected the query: {body.get('error', body)}")

    if "data" not in body:
        # The LABEL endpoints omit `data` entirely on an empty result - they
        # answer `{"status":"success"}` and nothing else. `body["data"]` raises
        # KeyError there, which surfaces as a broken connector when the truth is
        # a quiet window.
        #
        # `query_range` does NOT do this: it sends `data` with an empty `result`
        # and a full `stats` block even when nothing matched. Both measured
        # against a live Loki rather than read from the documentation, which is
        # why the two callers below say different things.
        if empty is REPORT_ABSENCE:
            raise ToolError(
                f"loki answered {path} with no `data`. The label endpoints do "
                "that when a window is empty; this one always sends it, so this "
                "is a change in Loki rather than a quiet window."
            )
        return empty
    return body["data"]


async def query_range(arguments: dict[str, Any]) -> Any:
    """Run a LogQL query over a window.

    The one Lethe leans on: clustering needs a window of lines, and a single
    instant is not a window.
    """
    for required in ("query", "start", "end"):
        if not arguments.get(required):
            raise ToolError(f"query_range needs a `{required}`")

    limit = int(arguments.get("limit", DEFAULT_LIMIT))
    if limit > MAX_LIMIT:
        raise ToolError(
            f"limit={limit} exceeds this connector's cap of {MAX_LIMIT}. Loki "
            "answers an oversized request with a 400 that reads like a malformed "
            "query, so it is refused here where the reason is legible."
        )

    direction = arguments.get("direction", "backward")
    if direction not in ("forward", "backward"):
        raise ToolError(f"direction must be 'forward' or 'backward', not {direction!r}")

    return await _get(
        "/loki/api/v1/query_range",
        {
            "query": arguments["query"],
            "start": arguments["start"],
            "end": arguments["end"],
            "limit": limit,
            "direction": direction,
        },
        # query_range always sends `data`, empty window included, so absence
        # would be new behaviour rather than silence. Reported, because a
        # fabricated `{"result": []}` here is indistinguishable from a service
        # that genuinely logged nothing.
        empty=REPORT_ABSENCE,
    )


async def labels(arguments: dict[str, Any]) -> Any:
    """Label names, or one label's values when `name` is given.

    Both in one tool because they answer one question - what can I select on -
    and because the manifest declares one. Lethe cannot build a LogQL selector
    from names alone.
    """
    params: dict[str, Any] = {}
    for optional in ("start", "end"):
        if arguments.get(optional):
            params[optional] = arguments[optional]

    name = arguments.get("name")
    if name:
        return await _get(_label_values_path(str(name)), params, empty=[])
    return await _get("/loki/api/v1/labels", params, empty=[])


_TIMESTAMP = {"type": "string", "description": "RFC3339 or a unix nanosecond timestamp."}


def build_server() -> BaseMCPServer:
    """The Loki connector, with exactly the tools Lethe declares."""
    server = BaseMCPServer(name="loki")

    server.register(
        Tool(
            name="loki.query_range",
            description="Run a LogQL query over a time window.",
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A LogQL expression."},
                    "start": _TIMESTAMP,
                    "end": _TIMESTAMP,
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum entries, up to {MAX_LIMIT}.",
                    },
                    "direction": {"type": "string", "enum": ["forward", "backward"]},
                },
                "required": ["query", "start", "end"],
            },
            handler=query_range,
        )
    )
    server.register(
        Tool(
            name="loki.labels",
            description="List label names, or the values of one named label.",
            schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Omit for label names; give one to list its values.",
                    },
                    "start": _TIMESTAMP,
                    "end": _TIMESTAMP,
                },
            },
            handler=labels,
        )
    )
    return server
