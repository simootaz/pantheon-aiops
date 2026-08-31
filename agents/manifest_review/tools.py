"""Connector tools Aegis is allowed to call, and the adapters that shape them.

WHY THIS FILE CAME BACK
-------------------------
It was empty, and said so: *"They come back when there is something behind
them."* `connectors/github` exists now, so there is.

Three tools, and each earns its place by being needed to answer one question:

* `github.pull_request` — what did this change from? The `files` listing names
  what changed and carries neither sha, so without this there is no *before*.
* `github.diff` — which files changed, and how. `status` is what says whether a
  file existed at the base at all.
* `github.file_at` — the bytes, at a sha. See `sources.py` for why this rather
  than applying the patch.

WHAT IS STILL NOT DECLARED
----------------------------
`kubernetes.get` and `kubernetes.list`, which the manifest carried for two
phases and nothing called. Aegis reviews a change, and nothing about the
cluster changes what a diff removed - a readiness probe deleted from a manifest
is deleted whatever the cluster currently says.

They would answer a different question: what the change will *land on*. That is
a real question and this agent does not ask it.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.github import tools as github


def _pull_request(**kwargs: Any) -> Awaitable[Any]:
    return github.pull_request(
        {"repository": kwargs["repository"], "pull_request": kwargs["pull_request"]}
    )


def _diff(**kwargs: Any) -> Awaitable[Any]:
    return github.diff({"repository": kwargs["repository"], "pull_request": kwargs["pull_request"]})


def _file_at(**kwargs: Any) -> Awaitable[Any]:
    return github.file_at(
        {"repository": kwargs["repository"], "path": kwargs["path"], "ref": kwargs["ref"]}
    )


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "github.pull_request": _pull_request,
    "github.diff": _diff,
    "github.file_at": _file_at,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has.

    Silent about the rest on purpose: a declared tool with no implementation
    stays unbound and raises `ToolNotBound` at call time, which reads as "the
    connector is not running" rather than "you may not" - a distinction
    `tool_binding.py` exists to preserve.
    """
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
