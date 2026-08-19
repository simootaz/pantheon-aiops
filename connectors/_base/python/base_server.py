"""The MCP server shape every Python connector repeats.

Mirrors `pkg/mcpserver` on the Go side deliberately, field for field, so a
connector reads the same in either language. In particular `Tool.mutating` is a
**field, not a naming convention**: the read/write split is the thing guardrails
will hang off at Phase 3, and inferring it from a verb in the tool name would
make the security boundary a spelling exercise.

READ-ONLY IN PHASE 1
--------------------
No mutating tool exists yet, and `tests/unit/test_connectors.py` asserts that
rather than trusting it. The moment one does exist it needs the approval path,
and proving none exists is cheaper than discovering one that skipped it.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mcp import types
from mcp.server import Server

#: A tool handler: the raw argument object in, a JSON-serialisable result out.
Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolError(RuntimeError):
    """A tool failed in a way the calling agent should see, not a crash."""


@dataclass(slots=True)
class Tool:
    """One callable exposed over MCP.

    `schema` is the JSON Schema for the argument object. Hand-writing one that
    mirrors a contract is forbidden across this repository; where a tool's
    arguments are a contract shape, it comes from `core/contracts/`.
    """

    name: str
    description: str
    schema: dict[str, Any]
    handler: Handler
    #: True when the tool changes the state of the system it talks to. Mutating
    #: tools must pass through `core/guardrails` before dispatch (Phase 3).
    mutating: bool = False


@dataclass(slots=True)
class BaseMCPServer:
    """Tool registry and dispatch, shared by every Python connector.

    Connectors subclass nothing; they build one of these and register tools.
    Composition rather than inheritance because a connector's only job is to
    supply tools, and an abstract method would invite it to override dispatch.
    """

    name: str
    version: str = "0.2.0"
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """Add a tool. Duplicate names are fatal rather than last-one-wins."""
        if tool.name in self._tools:
            raise ValueError(
                f"{self.name}: tool {tool.name!r} is registered twice. Two tools "
                "answering to one name makes dispatch a coin toss."
            )
        self._tools[tool.name] = tool

    @property
    def tools(self) -> dict[str, Tool]:
        return dict(self._tools)

    @property
    def read_only(self) -> bool:
        """Whether this server exposes no state-changing tool at all."""
        return not any(tool.mutating for tool in self._tools.values())

    def describe(self) -> list[types.Tool]:
        """The MCP tool list, as the protocol wants it."""
        return [
            types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.schema,
            )
            for tool in self._tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke a tool by name.

        Errors are returned as errors rather than swallowed. A connector that
        answers a failed query with an empty result set teaches an agent that
        the system is healthy, which is the worst possible lie to tell an
        anomaly detector.
        """
        if name not in self._tools:
            raise ToolError(f"{self.name}: no tool named {name!r}. Have: {sorted(self._tools)}")
        return await self._tools[name].handler(arguments or {})

    def build(self) -> Server[Any, Any]:
        """Wire this registry into a real MCP `Server` for stdio transport."""
        server: Server[Any, Any] = Server(self.name, version=self.version)

        @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
        async def _list() -> list[types.Tool]:
            return self.describe()

        @server.call_tool()  # type: ignore[untyped-decorator]
        async def _call(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
            result = await self.call(name, arguments)
            return [types.TextContent(type="text", text=json.dumps(result, default=str))]

        return server
