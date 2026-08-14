"""Shared scaffolding for the Python MCP connectors.

The leading underscore keeps this package out of connector auto-discovery in
core.registry - it is a base, not a connector. Go connectors build on
pkg/mcpserver instead.

Phase: 1 - Contracts & First Agent Path
"""

# TODO: Phase 1 - re-export the Python connector base
