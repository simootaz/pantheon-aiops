"""The four read-only GitLab tools the agent manifests declare, and nothing else.

The names here are exactly the strings in `agents/ci_triage/manifest.yaml` and
`agents/dora/manifest.yaml`: `gitlab.pipeline`, `gitlab.jobs`, `gitlab.diff` and
`gitlab.merge_requests`.

READ-ONLY
---------
GitLab's write surface is large and consequential: `POST /projects/:id/pipeline`
triggers a run, `DELETE /projects/:id/repository/branches/:branch` removes a
branch, and the merge endpoint lands code. None of it is reachable from here.
The path allowlist is the mechanism - a denylist would have to know today about
the endpoint added in the next release.

THE TOKEN TRAVELS IN A HEADER, NEVER IN THE URL
------------------------------------------------
GitLab accepts `?private_token=` and it works. It is also a credential in a
query string, which means it is in the reverse proxy's access log, in the
browser history of whoever pasted the URL, and in any Referer the page emits.

`PRIVATE-TOKEN` is a header, so none of that happens. This is the same decision
`core/cerberus/store/kinds.py` makes about HTTP credentials, for the same
reason, and it is asserted rather than described - see
`tests/unit/test_connectors.py`.

THE PROJECT ID IS VALIDATED BEFORE IT IS SUBSTITUTED
------------------------------------------------------
A GitLab project is addressed either by numeric id or by URL-encoded path -
`group%2Fproject`. A raw slash escapes the path segment it was meant to fill,
and a value checked once it is already inside a URL is a value checked too late.
The same lesson `connectors/loki/tools.py` records about label names.

Encoding happens here rather than being expected of the caller. A caller that
forgot would produce a URL that reaches a *different* endpoint and returns a
plausible answer, which is the failure that does not look like one.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

#: GitLab paths this connector may reach, with `<>` placeholders substituted
#: only through `_project_path`, which validates first.
READ_PATHS = (
    "/api/v4/projects/<id>/pipelines/<pipeline>",
    "/api/v4/projects/<id>/pipelines/<pipeline>/jobs",
    "/api/v4/projects/<id>/merge_requests",
    "/api/v4/projects/<id>/merge_requests/<iid>/changes",
)

#: A project reference: a numeric id, or a path like `group/sub/project`.
#:
#: Anchored. An unanchored pattern matches a prefix of a hostile string and
#: passes the rest along - which is exactly how a traversal gets into a URL.
PROJECT = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_.\-/]*\Z")

#: A `..` segment, refused separately.
#:
#: `quote(safe="")` already neutralises one - `group/../x` encodes to
#: `group%2F..%2Fx`, which GitLab reads as a project name and does not find. So
#: this is defence in depth rather than the load-bearing check.
#:
#: Kept anyway, and this is the reason: a validator that ACCEPTS a traversal is
#: one careless caller away from being the only thing that mattered. The day
#: somebody builds a path without going through `_project_path`, the pattern
#: that said "this is a fine project reference" is what they will have trusted.
TRAVERSAL = re.compile(r"(\A|/)\.\.(/|\Z)")

#: Numeric-only references: a pipeline id, a merge request iid.
NUMERIC = re.compile(r"\A[0-9]+\Z")

#: The concrete forms of the templated entries above, so one allowlist covers
#: both the fixed shape and the parameterised ones.
_CONCRETE = tuple(
    re.compile(
        "\\A"
        + pattern.replace("<id>", "[^/]+")
        .replace("<pipeline>", "[0-9]+")
        .replace("<iid>", "[0-9]+")
        + "\\Z"
    )
    for pattern in READ_PATHS
)

TIMEOUT_SECONDS = 30.0

#: GitLab pages at 20 by default and caps at 100. Asked for explicitly, because
#: a silently truncated list of merge requests looks like a quiet week.
DEFAULT_PER_PAGE = 100
MAX_PER_PAGE = 100


def _project_path(project: str) -> str:
    """URL-encode a project reference, or refuse it.

    Validation before substitution. `quote(safe="")` is what turns
    `group/project` into `group%2Fproject`; without the empty `safe` the slash
    survives and addresses a different endpoint.
    """
    if not PROJECT.match(project) or TRAVERSAL.search(project):
        raise ToolError(
            f"{project!r} is not a GitLab project reference. Expected a numeric id "
            "or a path like 'group/project' - it is substituted into a request "
            "path, so it is validated rather than escaped after the fact."
        )
    return quote(project, safe="")


def _numeric(value: Any, *, what: str) -> str:
    if not NUMERIC.match(str(value)):
        raise ToolError(f"{what} must be a number, not {value!r}")
    return str(value)


def _allowed(path: str) -> bool:
    """Whether this connector may reach `path`.

    Pure, so the allowlist can be tested without opening a socket.
    """
    return any(pattern.match(path) for pattern in _CONCRETE)


def _headers() -> dict[str, str]:
    """Authentication, in a header.

    A missing token is not an error here. GitLab serves public projects
    unauthenticated, and refusing to start without one would make a public
    read impossible in order to prevent a private read that GitLab already
    refuses on its own.
    """
    token = get_settings().gitlab.token
    return {"PRIVATE-TOKEN": token.get_secret_value()} if token is not None else {}


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """One read against GitLab, with the failure surfaced rather than hidden."""
    if not _allowed(path):
        raise ToolError(
            f"{path!r} is not one of this connector's read paths {list(READ_PATHS)}. "
            "GitLab's pipeline-trigger, branch-delete and merge endpoints are "
            "deliberately unreachable."
        )

    base = get_settings().gitlab.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}{path}", params=params or {}, headers=_headers())
    except httpx.HTTPError as error:
        raise ToolError(f"gitlab at {base} is unreachable: {error}") from error

    if response.status_code == 401:
        raise ToolError(
            "gitlab rejected the credential. GITLAB_TOKEN is unset or expired - "
            "reported as an authentication failure rather than as an empty result, "
            "which is what a caller would otherwise read it as."
        )
    if response.status_code == 404:
        # 404 rather than 403 is what GitLab answers for a project the token
        # cannot see, deliberately: existence is itself a disclosure. So this
        # says both, because "wrong id" and "no access" lead to different fixes.
        raise ToolError(
            f"gitlab has no {path} visible to this token. GitLab answers 404 for a "
            "project a token cannot see as well as for one that does not exist, so "
            "this is either the wrong reference or a missing scope."
        )
    if response.status_code >= 400:
        raise ToolError(f"gitlab returned {response.status_code}: {response.text[:200]}")

    return response.json()


async def pipeline(arguments: dict[str, Any]) -> Any:
    """One pipeline, whole. Status, ref, sha, timings."""
    project = _project_path(str(arguments.get("project", "")))
    number = _numeric(arguments.get("pipeline"), what="pipeline")
    return await _get(f"/api/v4/projects/{project}/pipelines/{number}")


async def jobs(arguments: dict[str, Any]) -> Any:
    """Every job in one pipeline.

    The failing job's name and stage are what a triage agent needs; the pipeline
    alone says only that something failed.
    """
    project = _project_path(str(arguments.get("project", "")))
    number = _numeric(arguments.get("pipeline"), what="pipeline")
    return await _get(
        f"/api/v4/projects/{project}/pipelines/{number}/jobs",
        {"per_page": _per_page(arguments)},
    )


async def merge_requests(arguments: dict[str, Any]) -> Any:
    """Merge requests, newest first.

    `state` is passed through rather than defaulted to `merged`. DORA lead time
    needs merged ones and a review-latency question needs open ones, and a
    default here would be one of those two silently answering the other.
    """
    project = _project_path(str(arguments.get("project", "")))
    params: dict[str, Any] = {"per_page": _per_page(arguments), "order_by": "updated_at"}
    for optional in ("state", "target_branch", "updated_after"):
        if arguments.get(optional):
            params[optional] = arguments[optional]
    return await _get(f"/api/v4/projects/{project}/merge_requests", params)


async def diff(arguments: dict[str, Any]) -> Any:
    """The changes in one merge request.

    Returns GitLab's `changes` shape: a list of per-file entries carrying
    `old_path`, `new_path` and a unified `diff` string.

    NOT what Aegis consumes directly. `agents/manifest_review/` reviews parsed
    `before`/`after` manifests, and a unified diff is neither - turning one into
    the other means applying the diff to the file at the base sha, which needs a
    second read this connector does not do yet. Stated rather than papered over:
    handing Aegis a text diff and calling it a manifest would produce a review of
    nothing that looked like a review.
    """
    project = _project_path(str(arguments.get("project", "")))
    iid = _numeric(arguments.get("merge_request"), what="merge_request")
    return await _get(f"/api/v4/projects/{project}/merge_requests/{iid}/changes")


def _per_page(arguments: dict[str, Any]) -> int:
    requested = int(arguments.get("per_page", DEFAULT_PER_PAGE))
    if requested > MAX_PER_PAGE:
        raise ToolError(
            f"per_page={requested} exceeds GitLab's cap of {MAX_PER_PAGE}. GitLab "
            "silently clamps it, and a clamped list of merge requests looks like a "
            "quiet week rather than a truncated answer."
        )
    return requested


_PROJECT_ARG = {
    "type": "string",
    "description": "Numeric id, or path like 'group/project'. URL-encoded here.",
}


def build_server() -> BaseMCPServer:
    """The GitLab connector's tool registry. Read-only, and asserted to be."""
    server = BaseMCPServer(name="gitlab")
    server.register(
        Tool(
            name="pipeline",
            description="One pipeline: status, ref, sha and timings.",
            schema={
                "type": "object",
                "properties": {
                    "project": _PROJECT_ARG,
                    "pipeline": {"type": "integer", "description": "Pipeline id."},
                },
                "required": ["project", "pipeline"],
            },
            handler=pipeline,
        )
    )
    server.register(
        Tool(
            name="jobs",
            description="Every job in one pipeline, with stage and status.",
            schema={
                "type": "object",
                "properties": {
                    "project": _PROJECT_ARG,
                    "pipeline": {"type": "integer", "description": "Pipeline id."},
                    "per_page": {"type": "integer", "description": f"Max {MAX_PER_PAGE}."},
                },
                "required": ["project", "pipeline"],
            },
            handler=jobs,
        )
    )
    server.register(
        Tool(
            name="merge_requests",
            description="Merge requests, newest first. `state` is not defaulted.",
            schema={
                "type": "object",
                "properties": {
                    "project": _PROJECT_ARG,
                    "state": {"type": "string", "description": "opened, closed, merged, all."},
                    "target_branch": {"type": "string"},
                    "updated_after": {"type": "string", "description": "ISO-8601."},
                    "per_page": {"type": "integer", "description": f"Max {MAX_PER_PAGE}."},
                },
                "required": ["project"],
            },
            handler=merge_requests,
        )
    )
    server.register(
        Tool(
            name="diff",
            description="Per-file changes in one merge request, as unified diffs.",
            schema={
                "type": "object",
                "properties": {
                    "project": _PROJECT_ARG,
                    "merge_request": {"type": "integer", "description": "Merge request iid."},
                },
                "required": ["project", "merge_request"],
            },
            handler=diff,
        )
    )
    return server
