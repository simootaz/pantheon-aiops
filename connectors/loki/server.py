"""Runs the Loki connector as a real MCP server over stdio.

    python -m connectors.loki.server

Read-only. The tools are defined in `tools.py`; this file is transport only, so
the thing under test in `tests/integration/` is the same registry the server
serves rather than a parallel implementation of it.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import asyncio

from mcp.server.stdio import stdio_server

from connectors.loki.tools import build_server


async def main() -> None:
    registry = build_server()
    server = registry.build()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
