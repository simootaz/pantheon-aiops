"""Connector tools Aegis is allowed to call: none.

Aegis reviews a change it is given. The before/after manifests arrive on
`ctx.params`, and nothing about the cluster changes what the diff removed - a
readiness probe deleted from a manifest is deleted whatever the cluster
currently says.

WHY THE MANIFEST DECLARES AN EMPTY TOOLSET
--------------------------------------------
It previously declared `kubernetes.get`, `kubernetes.list`, `gitlab.diff` and
`github.diff`. None were called: `connectors/gitlab` and `connectors/github` are
Phase 4 stubs, and the Kubernetes reads would answer a question Aegis does not
ask.

A declared tool the agent never calls is an allowlist entry nobody uses, and the
allowlist is the thing that makes an agent's reach checkable by reading its
manifest. Declaring four unused tools makes that reading wrong in the direction
that matters.

They come back when there is something behind them. `gitlab.diff` and
`github.diff` are what would let Aegis fetch a change rather than be handed one,
and that is a Phase 4 capability with a Phase 4 connector.

WHY THERE IS NO `attach` HERE
-------------------------------
Every other agent's `tools.py` has one, and this one had one too - a loop over
an empty mapping, written so the shape would match. The per-module coverage
floor failed it at 46%, correctly: a loop that cannot execute is not a binding
mechanism, it is an unexecutable claim that one exists.

`BaseAgent.bind_tools` is optional by design, so Aegis does not override it.
The agent that gains a tool adds both back together, which is one change rather
than a mechanism sitting unused waiting for a caller.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: Empty, and asserted to be by `test_aegis_declares_no_tools_and_implements_none`.
IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {}
