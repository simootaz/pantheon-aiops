"""Mnemosyne's tools: one, and the runtime provides it.

`memory.recall` closes over the investigation store and the tenant of the run
in progress, so it cannot be a module-level adapter the way a connector tool is
- there is no store at import time, and there must not be a global one. The
dispatcher builds it per step and puts it on `AgentContext.provided`;
`BaseAgent.run` registers it only because the manifest declares it.

So there is no `IMPLEMENTATIONS` table here to fill an allowlist from. The
reachability guard reads `PROVIDED` instead and checks that every declared
tool is one the runtime knows how to provide.

Phase: 5 - Proactive Flow
"""

from __future__ import annotations

from agents._base.tool_binding import BoundTools
from core.memory.recall import TOOL_NAME

#: Declared tools the runtime provides. The only kind Mnemosyne has.
PROVIDED: frozenset[str] = frozenset({TOOL_NAME})

#: For the guard that checks every dispatchable agent's declared tools against
#: what implements them: nothing here, by design - see the module docstring.
IMPLEMENTATIONS: dict[str, object] = {}


def attach(tools: BoundTools) -> None:
    """Nothing to attach. The runtime registers `memory.recall` itself."""
