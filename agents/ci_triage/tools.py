"""Connector tools Hephaestus is allowed to call, and the adapters that shape them.

Three, and each answers one question a triage needs: what run is this
(`actions_run`, for its head_sha), what else ran at that commit
(`workflow_runs`), and how each job finished (`jobs`).

WHAT IS NO LONGER DECLARED
----------------------------
`gitlab.pipeline`, `gitlab.jobs`, `gitlab.diff` and `github.diff`.

The GitLab three go because this deployment uses GitHub. `connectors/gitlab`
exists and is tested; it is simply not what this agent reaches for, and a
declared tool nobody calls makes an agent's reach unreadable from the one place
it is supposed to be readable.

`github.diff` goes because triage does not read the change. Linking a failure to
the change that caused it needs the parent commit's runs, and the commits API is
not reachable - see `triage.py`. A tool declared for a capability that is
explicitly not built is worse than no tool: it says the capability exists.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agents._base.tool_binding import BoundTools
from connectors.github import tools as github


def _actions_run(**kwargs: Any) -> Awaitable[Any]:
    return github.actions_run({"repository": kwargs["repository"], "run": kwargs["run"]})


def _workflow_runs(**kwargs: Any) -> Awaitable[Any]:
    return github.workflow_runs(
        {"repository": kwargs["repository"], "head_sha": kwargs["head_sha"]}
    )


def _jobs(**kwargs: Any) -> Awaitable[Any]:
    return github.jobs({"repository": kwargs["repository"], "run": kwargs["run"]})


#: Declared name to implementation. A name the manifest does not declare is
#: refused by `register`, so this cannot widen the allowlist - only fill it.
IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {
    "github.actions_run": _actions_run,
    "github.workflow_runs": _workflow_runs,
    "github.jobs": _jobs,
}


def attach(tools: BoundTools) -> None:
    """Register every implementation the toolset declares and this module has."""
    for name, implementation in IMPLEMENTATIONS.items():
        if name in tools.declared:
            tools.register(name, implementation)
