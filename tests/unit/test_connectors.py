"""Guards over the connector layer: read-only, scoped, and honestly wired.

The read/write split lives here rather than in an agent, because a connector is
where a capability physically exists. An agent that cannot reach a write tool is
safe by construction; an agent trusted not to call one is safe by convention.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from connectors.alertmanager.tools import build_server as build_alertmanager
from connectors.prometheus import tools as prometheus_tools
from connectors.prometheus.tools import build_server as build_prometheus
from core.registry.loader import for_codename
from tests.mechanism import read_data

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTORS = REPO_ROOT / "connectors"

#: Every connector that ships a Python MCP server in Phase 1.
SERVERS = {"prometheus": build_prometheus, "alertmanager": build_alertmanager}


# --- read-only, proven rather than trusted -----------------------------------


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_no_connector_exposes_a_mutating_tool(name: str) -> None:
    """Phase 1 is read-only, and that is asserted rather than assumed.

    `mutating` is a field on the Tool, mirroring `pkg/mcpserver` on the Go side,
    so this checks a declaration rather than guessing from a verb in a name. The
    moment a mutating tool exists it needs the approval path at Phase 3, and
    proving none exists is cheaper than discovering one that skipped it.
    """
    server = SERVERS[name]()
    mutating = sorted(tool.name for tool in server.tools.values() if tool.mutating)
    assert not mutating, (
        f"{name} exposes mutating tools {mutating} but Phase 1 has no approval "
        "path for them. See core/guardrails (Phase 3)."
    )
    assert server.read_only


def test_the_read_only_property_can_actually_be_false() -> None:
    """The control. A property hard-wired to True would prove nothing above."""
    server = BaseMCPServer(name="probe")
    server.register(
        Tool(name="probe.write", description="d", schema={}, handler=_noop, mutating=True)
    )
    assert not server.read_only


async def _noop(_arguments: dict[str, Any]) -> Any:  # pragma: no cover - never invoked
    return None


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_a_connector_reaches_only_its_declared_read_paths(name: str) -> None:
    """The HTTP paths are an allowlist, not a denylist.

    Prometheus ships `/api/v1/admin/tsdb/delete_series`; a denylist would have
    to know that in advance, and would not know about the next one.
    """
    module = {
        "prometheus": REPO_ROOT / "connectors/prometheus/tools.py",
        "alertmanager": REPO_ROOT / "connectors/alertmanager/tools.py",
    }[name]
    source = read_data(module)
    assert "READ_PATHS" in source, f"{name} has no read-path allowlist"
    for forbidden in ("admin", "delete", "/-/reload", "silences POST"):
        assert f'"{forbidden}"' not in source, f"{name} names {forbidden!r} as a path"


async def test_a_path_outside_the_allowlist_is_refused() -> None:
    """The mechanism behind the guard above, exercised rather than inferred."""
    with pytest.raises(ToolError, match="deliberately unreachable"):
        await prometheus_tools._get("/api/v1/admin/tsdb/delete_series", {})


# --- the manifest and the connector describe the same tools ------------------


def test_the_prometheus_tools_are_exactly_what_argus_declares() -> None:
    """Both directions, so the allowlist has real subjects.

    A tool nobody declares is unreachable and therefore dead; a declaration
    nothing implements makes `ToolNotBound` the normal case rather than the
    exceptional one, which would train everyone to ignore it.
    """
    declared = set(for_codename("argus").tools)
    implemented = set(build_prometheus().tools)

    assert declared == implemented, (
        f"Argus declares {sorted(declared)}; the connector implements "
        f"{sorted(implemented)}. They have to be the same set."
    )


def test_every_registered_tool_carries_a_schema_and_a_description() -> None:
    """An agent picks a tool by reading these; blank ones make it guess."""
    for name, build in SERVERS.items():
        for tool in build().tools.values():
            assert tool.description.strip(), f"{name}: {tool.name} has no description"
            assert tool.schema.get("type") == "object", f"{name}: {tool.name} has no schema"


def test_registering_the_same_tool_twice_is_fatal() -> None:
    """Two tools answering to one name makes dispatch a coin toss."""
    server = BaseMCPServer(name="probe")
    tool = Tool(name="probe.read", description="d", schema={}, handler=_noop)
    server.register(tool)
    with pytest.raises(ValueError, match="registered twice"):
        server.register(tool)


async def test_calling_an_unknown_tool_names_the_ones_that_exist() -> None:
    server = build_prometheus()
    with pytest.raises(ToolError, match=r"prometheus\.query_range"):
        await server.call("prometheus.delete_everything")


# --- the connector is configured through core.config only --------------------


def test_no_connector_hardcodes_an_endpoint() -> None:
    """Covered by the global guard too; asserted here because it is the point.

    A connector with a baked-in URL is one that cannot be pointed at a different
    Prometheus, which is the entire reason the config module exists.
    """
    for path in sorted(CONNECTORS.rglob("*.py")):
        for node in ast.walk(ast.parse(read_data(path))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "://" not in node.value, (
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno} hardcodes {node.value!r}"
                )


def test_connectors_read_their_endpoint_from_the_settings_module() -> None:
    """Both connectors, so neither can drift onto its own default."""
    for module in ("connectors/prometheus/tools.py", "connectors/alertmanager/tools.py"):
        source = read_data(REPO_ROOT / module)
        assert "get_settings()" in source, f"{module} does not read core.config"


# --- the HTTP layer, with the network stubbed --------------------------------


def _stub(handler: Any) -> Any:
    """Patch httpx.AsyncClient so a tool talks to a transport, not a network."""
    import httpx

    class _Client(httpx.AsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    return _Client


def _ok(payload: dict[str, Any]) -> Any:
    import httpx

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


async def test_a_successful_query_returns_the_data_block(monkeypatch: Any) -> None:
    """Prometheus wraps everything in {status, data}; tools return the data."""
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", _stub(_ok({"status": "success", "data": {"resultType": "vector"}}))
    )
    result = await build_prometheus().call("prometheus.query_instant", {"query": "up"})
    assert result == {"resultType": "vector"}


async def test_a_prometheus_error_status_is_raised_not_returned(monkeypatch: Any) -> None:
    """`{"status": "error"}` with HTTP 200 is the shape that fools a naive client."""
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", _stub(_ok({"status": "error", "error": "parse error at char 4"}))
    )
    with pytest.raises(ToolError, match="parse error"):
        await build_prometheus().call("prometheus.query_instant", {"query": "sum((("})


async def test_an_http_error_is_raised_with_the_body(monkeypatch: Any) -> None:
    import httpx

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="bad request")

    monkeypatch.setattr(httpx, "AsyncClient", _stub(handler))
    with pytest.raises(ToolError, match="422"):
        await build_prometheus().call("prometheus.query_instant", {"query": "up"})


async def test_an_unreachable_prometheus_names_the_endpoint(monkeypatch: Any) -> None:
    """The message has to say *where* it tried, or an operator cannot act on it."""
    import httpx

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _stub(handler))
    with pytest.raises(ToolError, match="unreachable"):
        await build_prometheus().call("prometheus.query_instant", {"query": "up"})


@pytest.mark.parametrize(
    ("tool", "arguments", "missing"),
    [
        ("prometheus.query_instant", {}, "query"),
        ("prometheus.query_range", {"query": "up"}, "start"),
        ("prometheus.query_range", {"query": "up", "start": "1"}, "end"),
        ("prometheus.series", {}, "match"),
    ],
)
async def test_missing_arguments_are_named(
    tool: str, arguments: dict[str, Any], missing: str
) -> None:
    """An agent that gets "invalid request" cannot fix its call; name the field."""
    with pytest.raises(ToolError, match=missing):
        await build_prometheus().call(tool, arguments)


async def test_alertmanager_tools_reach_alertmanager(monkeypatch: Any) -> None:
    import httpx

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, "AsyncClient", _stub(handler))
    server = build_alertmanager()
    assert await server.call("alertmanager.list_alerts", {"silenced": False}) == []
    assert await server.call("alertmanager.list_silences", {}) == []
    assert seen == ["/api/v2/alerts", "/api/v2/silences"]


async def test_an_alertmanager_error_is_raised(monkeypatch: Any) -> None:
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", _stub(lambda _r: httpx.Response(503, text="unavailable"))
    )
    with pytest.raises(ToolError, match="503"):
        await build_alertmanager().call("alertmanager.list_alerts", {})


async def test_an_alertmanager_path_outside_the_allowlist_is_refused() -> None:
    from connectors.alertmanager import tools as alertmanager_tools

    with pytest.raises(ToolError, match="/api/v2/alerts"):
        await alertmanager_tools._get("/api/v2/silences/delete")


def test_the_registry_describes_itself_for_mcp() -> None:
    """`describe()` is what an MCP client reads to discover the tools."""
    described = build_prometheus().describe()
    assert {tool.name for tool in described} == set(build_prometheus().tools)
    assert all(tool.inputSchema.get("type") == "object" for tool in described)


def test_the_registry_builds_a_real_mcp_server() -> None:
    """Transport is the SDK's; this asserts the wiring, not the protocol."""
    server = build_prometheus().build()
    assert server.name == "prometheus"


async def test_optional_arguments_reach_prometheus_when_supplied(monkeypatch: Any) -> None:
    """`time`, `step` and the series window are optional and must be honoured.

    Not decoration: an agent that asks for a 5s step and silently gets the
    default reads a coarser series than it thinks it has, and draws a
    correspondingly wrong conclusion about how sharp a change was.
    """
    import httpx

    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json={"status": "success", "data": {}})

    monkeypatch.setattr(httpx, "AsyncClient", _stub(handler))
    server = build_prometheus()

    await server.call("prometheus.query_instant", {"query": "up", "time": "2026-01-01T00:00:00Z"})
    assert seen[-1]["time"] == "2026-01-01T00:00:00Z"

    await server.call(
        "prometheus.query_range",
        {"query": "up", "start": "1", "end": "2", "step": "5s"},
    )
    assert seen[-1]["step"] == "5s"

    await server.call("prometheus.series", {"match": ["up"], "start": "1", "end": "2"})
    assert seen[-1]["start"] == "1"
    assert seen[-1]["end"] == "2"


async def test_query_range_defaults_its_step(monkeypatch: Any) -> None:
    """Omitting `step` must produce a working query, not a Prometheus 400."""
    import httpx

    seen: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json={"status": "success", "data": {}})

    monkeypatch.setattr(httpx, "AsyncClient", _stub(handler))
    await build_prometheus().call(
        "prometheus.query_range", {"query": "up", "start": "1", "end": "2"}
    )
    assert seen[-1]["step"] == "15s"


async def test_the_stdio_entrypoint_wires_the_registry_to_the_transport(
    monkeypatch: Any,
) -> None:
    """`python -m connectors.prometheus.server` has to reach a real server.

    The transport is the SDK's, so both ends are stubbed and what is asserted is
    the wiring between them: that the registry built here is the one served,
    and that the streams are passed through rather than dropped.
    """
    import contextlib

    from connectors.prometheus import server as entrypoint

    served: dict[str, Any] = {}

    @contextlib.asynccontextmanager
    async def fake_stdio() -> Any:
        yield ("read", "write")

    class _Recorder:
        name = "prometheus"

        async def run(self, read: Any, write: Any, options: Any) -> None:
            served.update(read=read, write=write, options=options)

        def create_initialization_options(self) -> Any:
            return {"initialised": True}

    monkeypatch.setattr(entrypoint, "stdio_server", fake_stdio)
    monkeypatch.setattr(
        entrypoint, "build_server", lambda: type("R", (), {"build": lambda _self: _Recorder()})()
    )

    await entrypoint.main()

    assert served["read"] == "read"
    assert served["write"] == "write"
    assert served["options"] == {"initialised": True}
