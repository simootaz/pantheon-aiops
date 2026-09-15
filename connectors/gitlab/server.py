"""Runs the GitLab connector as a real MCP server over stdio.

    python -m connectors.gitlab.server

Read-only. The tools are defined in `tools.py`; this file is transport only, so
the thing under test is the same registry the server serves rather than a
parallel implementation of it.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import asyncio

from mcp.server.stdio import stdio_server

from connectors.gitlab.tools import build_server


async def main() -> None:
    registry = build_server()
    server = registry.build()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
