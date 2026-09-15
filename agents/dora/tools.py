"""Connector tools Themis is allowed to call, and the adapter that shapes them.

One. Merged pull requests are the only source a merge frequency and a review
latency can come from.

WHAT IS NO LONGER DECLARED
----------------------------
`gitlab.pipeline`, `gitlab.merge_requests` and `github.actions_run`.

The GitLab two go because this deployment uses GitHub. `github.actions_run`
goes because Themis never looked at a workflow run: it was there for a
change-failure rate, which needs deployments linked to incidents and is not
computable here. A tool declared for a metric that is explicitly not produced
says the metric exists.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.github import tools as github


def _pull_requests(**kwargs: Any) -> Awaitable[Any]:
    return github.pull_requests(
        {"repository": kwargs["repository"], "state": kwargs.get("state", "closed")}
    )


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "github.pull_requests": _pull_requests,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has."""
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
