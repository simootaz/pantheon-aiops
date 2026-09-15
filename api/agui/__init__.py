"""AG-UI edge: Pantheon's agentic UI runtime.

Replaces the bespoke WebSocket layer that used to live in api/ws/. Every
frontend interaction flows through typed AG-UI events over SSE, so any
AG-UI-compatible client can drive Pantheon without bespoke integration.

AG-UI event types are imported from `ag_ui.core` and never redefined here.

See docs/adr/0006-agentic-ui-protocols.md.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from api.agui.endpoint import router

__all__ = ["router"]
