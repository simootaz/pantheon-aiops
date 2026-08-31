"""The four read-only GitHub tools the agent manifests declare, and nothing else.

The names here are exactly the strings in `agents/ci_triage/manifest.yaml` and
`agents/dora/manifest.yaml`: `github.actions_run`, `github.jobs`,
`github.pull_requests` and `github.diff`.

READ-ONLY
---------
GitHub's write surface is the whole product: `POST /repos/{o}/{r}/merges` lands
code, `PUT /pulls/{n}/merge` merges, `DELETE /git/refs/{ref}` removes a branch,
and `POST /actions/runs/{id}/rerun` spends money. None of it is reachable from
here. The path allowlist is the mechanism - a denylist would have to know today
about the endpoint added in the next release.

RATE LIMITING IS NOT AN AUTHENTICATION FAILURE
------------------------------------------------
GitHub answers 403 for both. They are completely different problems: one is
fixed by waiting, the other by fixing a token, and telling them apart needs
`X-RateLimit-Remaining`.

Conflating them sends whoever is on call to check a credential that is fine,
which is the most expensive kind of wrong error message - it is confident, it is
specific, and it is about the wrong system. So the remaining count is read and
the reset time is named in the message.

THE API VERSION IS PINNED
---------------------------
`X-GitHub-Api-Version` is how GitHub versions its REST API. Unset, a request
gets whatever the current default is, so a response shape can change under a
running deployment without anything in this repository changing. That failure
arrives as a parse error months after the last commit that could have caused it.

THE HOST IS A SETTING
-----------------------
`GITHUB_API_URL`, defaulting to github.com. A guard in
`tests/unit/test_centralized_config.py` caught this hardcoded, and it was right
to: an endpoint written into a connector is one that cannot be pointed at GitHub
Enterprise without a release.

`owner/repo` IS TWO SEGMENTS, AND STAYS TWO
---------------------------------------------
Unlike GitLab, GitHub does not URL-encode the slash: the path really is
`/repos/owner/repo/...`. So the slash is legitimate and exactly one is allowed,
with each half validated against what GitHub accepts. A second slash would add a
path segment, and a value checked once it is already inside a URL is a value
checked too late.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from connectors._base.python.base_server import BaseMCPServer, Tool, ToolError
from core.config import get_settings

#: The REST API version this connector is written against. Pinned rather than
#: defaulted - see the module docstring.
API_VERSION = "2022-11-28"

#: Paths this connector may reach. `<owner>/<repo>` is substituted only through
#: `_repo_path`, which validates first.
READ_PATHS = (
    "/repos/<owner>/<repo>/actions/runs/<run>",
    "/repos/<owner>/<repo>/actions/runs/<run>/jobs",
    "/repos/<owner>/<repo>/pulls",
    "/repos/<owner>/<repo>/pulls/<number>/files",
    "/repos/<owner>/<repo>/contents/<path>",
)

#: What GitHub accepts in an owner or repository name. Anchored: an unanchored
#: pattern matches a prefix of a hostile string and passes the rest along.
SEGMENT = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._\-]*\Z")

NUMERIC = re.compile(r"\A[0-9]+\Z")

#: A path inside a repository. Slashes are legitimate - `k8s/base/x.yaml` is one
#: file - so this is the one place a multi-segment value is correct.
#:
#: An ALLOWLIST of characters rather than a denylist of dangerous ones, which is
#: the same choice the read-path allowlist makes: a denylist has to know today
#: about the character that turns out to matter tomorrow. A leading slash and any
#: `..` segment are refused outright.
REPO_FILE = re.compile(r"\A(?!/)(?!.*(?:\A|/)\.\.(?:/|\Z))[A-Za-z0-9._/\-]+\Z")

#: A git object id, or a ref name. Refs are validated to the same character
#: class as a path segment: a ref goes into a query parameter here rather than a
#: path, but one containing a newline would split a header if this ever moved.
REF = re.compile(r"\A[A-Za-z0-9._\-/]+\Z")

_CONCRETE = tuple(
    re.compile(
        "\\A"
        + pattern.replace("<owner>", "[^/]+")
        .replace("<repo>", "[^/]+")
        .replace("<run>", "[0-9]+")
        .replace("<number>", "[0-9]+")
        .replace("<path>", ".+")
        + "\\Z"
    )
    for pattern in READ_PATHS
)

TIMEOUT_SECONDS = 30.0

#: GitHub pages at 30 by default and caps at 100. Asked for explicitly, because
#: a silently truncated list of pull requests looks like a quiet week.
DEFAULT_PER_PAGE = 100
MAX_PER_PAGE = 100


def _repo_path(repository: str) -> str:
    """Split `owner/repo` and validate both halves, or refuse.

    Returned as `owner/repo` rather than encoded: GitHub's path really is two
    segments, so encoding the slash would address an endpoint that does not
    exist. That is the opposite of the GitLab connector's rule and for the same
    underlying reason - the check has to match how the API actually addresses
    things, not how another one does.
    """
    owner, separator, repo = repository.partition("/")
    if not separator or not SEGMENT.match(owner) or not SEGMENT.match(repo):
        raise ToolError(
            f"{repository!r} is not a GitHub repository. Expected exactly "
            "'owner/repo' - it is substituted into a request path, so it is "
            "validated rather than escaped after the fact."
        )
    return f"{owner}/{repo}"


def _repo_file(path: str) -> str:
    """A path inside the repository, or refuse it.

    Not encoded. `/contents/k8s/base/deployment.yaml` is how the endpoint is
    addressed, so percent-encoding the slashes would name a file that does not
    exist - the same rule as `owner/repo`, applied to a longer path.
    """
    if not REPO_FILE.match(path):
        raise ToolError(
            f"{path!r} is not a path inside a repository. Expected something like "
            "'k8s/base/deployment.yaml' - no leading slash, no '..' segment."
        )
    return path


def _ref(ref: str) -> str:
    if not REF.match(ref):
        raise ToolError(f"{ref!r} is not a git ref or object id")
    return ref


def _numeric(value: Any, *, what: str) -> str:
    if not NUMERIC.match(str(value)):
        raise ToolError(f"{what} must be a number, not {value!r}")
    return str(value)


def _allowed(path: str) -> bool:
    """Whether this connector may reach `path`. Pure, so it needs no socket."""
    return any(pattern.match(path) for pattern in _CONCRETE)


def _headers() -> dict[str, str]:
    """Accept, API version, and the credential - in headers, never the URL.

    A missing token is not an error. GitHub serves public repositories
    unauthenticated at a lower rate limit, and refusing to start without one
    would make a public read impossible in order to prevent a private read
    GitHub already refuses on its own.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    token = get_settings().github.token
    if token is not None:
        headers["Authorization"] = f"Bearer {token.get_secret_value()}"
    return headers


def _refuse_403(response: httpx.Response, path: str) -> None:
    """Say which 403 this is.

    GitHub answers 403 for a rate limit and for a credential problem, and they
    are fixed differently - one by waiting, one by fixing a token. Reporting
    both as "forbidden" sends whoever is on call to check a credential that is
    fine.
    """
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining == "0":
        reset = response.headers.get("X-RateLimit-Reset", "an unstated time")
        raise ToolError(
            f"github rate-limited this request; the quota resets at {reset} "
            "(unix seconds). This is not a credential problem - an unauthenticated "
            "client gets 60 requests an hour, and a token raises it to 5000."
        )
    raise ToolError(
        f"github refused {path} with 403 and quota remaining. The token is "
        "present but lacks a scope for this resource, or SSO authorisation for "
        "the organisation has not been granted."
    )


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    """One read against GitHub, with the failure surfaced rather than hidden."""
    if not _allowed(path):
        raise ToolError(
            f"{path!r} is not one of this connector's read paths {list(READ_PATHS)}. "
            "GitHub's merge, branch-delete and workflow-rerun endpoints are "
            "deliberately unreachable."
        )

    base = get_settings().github.base
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base}{path}", params=params or {}, headers=_headers())
    except httpx.HTTPError as error:
        raise ToolError(f"github at {base} is unreachable: {error}") from error

    if response.status_code == 401:
        raise ToolError(
            "github rejected the credential. GITHUB_TOKEN is unset, expired or "
            "revoked - reported as an authentication failure rather than as an "
            "empty result, which is what a caller would otherwise read it as."
        )
    if response.status_code == 403:
        _refuse_403(response, path)
    if response.status_code == 404:
        # 404 rather than 403 is what GitHub answers for a private repository the
        # token cannot see, deliberately: existence is itself a disclosure. So
        # this says both, because "wrong name" and "no access" lead to different
        # fixes.
        raise ToolError(
            f"github has no {path} visible to this token. GitHub answers 404 for a "
            "private repository a token cannot see as well as for one that does not "
            "exist, so this is either the wrong name or a missing scope."
        )
    if response.status_code >= 400:
        raise ToolError(f"github returned {response.status_code}: {response.text[:200]}")

    return response.json()


async def actions_run(arguments: dict[str, Any]) -> Any:
    """One workflow run: conclusion, head sha, timings."""
    repository = _repo_path(str(arguments.get("repository", "")))
    run = _numeric(arguments.get("run"), what="run")
    return await _get(f"/repos/{repository}/actions/runs/{run}")


async def jobs(arguments: dict[str, Any]) -> Any:
    """Every job in one workflow run.

    The failing job's name and step are what a triage agent needs; the run alone
    says only that something failed.
    """
    repository = _repo_path(str(arguments.get("repository", "")))
    run = _numeric(arguments.get("run"), what="run")
    return await _get(
        f"/repos/{repository}/actions/runs/{run}/jobs", {"per_page": _per_page(arguments)}
    )


async def pull_requests(arguments: dict[str, Any]) -> Any:
    """Pull requests, most recently updated first.

    `state` is passed through rather than defaulted. GitHub's own default is
    `open`, which silently answers a lead-time question - which needs closed
    ones - with the wrong set entirely.
    """
    repository = _repo_path(str(arguments.get("repository", "")))
    params: dict[str, Any] = {
        "per_page": _per_page(arguments),
        "sort": "updated",
        "direction": "desc",
    }
    for optional in ("state", "base"):
        if arguments.get(optional):
            params[optional] = arguments[optional]
    return await _get(f"/repos/{repository}/pulls", params)


async def diff(arguments: dict[str, Any]) -> Any:
    """The files changed in one pull request.

    Returns GitHub's `files` shape: per-file entries carrying `filename`,
    `status`, and a `patch` string.

    NOT what Aegis consumes directly. `agents/manifest_review/` reviews parsed
    `before`/`after` manifests, and a patch is neither - turning one into the
    other means applying it to the file at the base sha, which needs a second
    read this connector does not do yet. Stated rather than papered over:
    handing Aegis a patch and calling it a manifest would produce a review of
    nothing that looked like a review.
    """
    repository = _repo_path(str(arguments.get("repository", "")))
    number = _numeric(arguments.get("pull_request"), what="pull_request")
    return await _get(
        f"/repos/{repository}/pulls/{number}/files", {"per_page": _per_page(arguments)}
    )


async def file_at(arguments: dict[str, Any]) -> Any:
    """One file's contents at one commit.

    THE REASON THIS EXISTS RATHER THAN APPLYING THE PATCH
    -------------------------------------------------------
    A pull request's `files` entries carry a unified `patch`, and reconstructing
    before/after from one is possible. It is also wrong here twice over.

    GitHub **omits `patch` entirely** for a file above roughly 20k of diff, and
    for anything it considers binary. A reviewer that reconstructed from patches
    would silently skip exactly the large manifest changes most worth reviewing,
    and produce a clean report.

    And applying a unified diff correctly is an algorithm with its own failure
    modes, none of which would be visible in the output - a mis-applied hunk
    yields a plausible document.

    Two reads at two shas yield the real bytes. It costs one extra request per
    file and removes both failure modes.

    GitHub returns base64 for a file under 1MB and **no content at all** above
    it, pointing at the blobs API instead. That case is reported rather than
    returned empty: an empty manifest reviews as "everything was removed".
    """
    repository = _repo_path(str(arguments.get("repository", "")))
    path = _repo_file(str(arguments.get("path", "")))
    ref = _ref(str(arguments.get("ref", "")))

    body = await _get(f"/repos/{repository}/contents/{path}", {"ref": ref})

    if isinstance(body, list):
        raise ToolError(
            f"{path} at {ref} is a directory, not a file. A directory listing "
            "reviewed as a manifest would parse as nothing and report a clean change."
        )
    if not body.get("content"):
        raise ToolError(
            f"github returned no content for {path} at {ref}. Files over 1MB are "
            "served through the blobs API instead, and an empty body reviewed as a "
            "manifest reads as 'everything was removed'."
        )
    return body


def _per_page(arguments: dict[str, Any]) -> int:
    requested = int(arguments.get("per_page", DEFAULT_PER_PAGE))
    if requested > MAX_PER_PAGE:
        raise ToolError(
            f"per_page={requested} exceeds GitHub's cap of {MAX_PER_PAGE}. GitHub "
            "silently clamps it, and a clamped list of pull requests looks like a "
            "quiet week rather than a truncated answer."
        )
    return requested


_REPO_ARG = {
    "type": "string",
    "description": "Exactly 'owner/repo'. Both halves are validated before use.",
}
_PER_PAGE_ARG = {"type": "integer", "description": f"Max {MAX_PER_PAGE}."}


def build_server() -> BaseMCPServer:
    """The GitHub connector's tool registry. Read-only, and asserted to be."""
    server = BaseMCPServer(name="github")
    server.register(
        Tool(
            name="actions_run",
            description="One workflow run: conclusion, head sha and timings.",
            schema={
                "type": "object",
                "properties": {
                    "repository": _REPO_ARG,
                    "run": {"type": "integer", "description": "Workflow run id."},
                },
                "required": ["repository", "run"],
            },
            handler=actions_run,
        )
    )
    server.register(
        Tool(
            name="jobs",
            description="Every job in one workflow run, with step and conclusion.",
            schema={
                "type": "object",
                "properties": {
                    "repository": _REPO_ARG,
                    "run": {"type": "integer", "description": "Workflow run id."},
                    "per_page": _PER_PAGE_ARG,
                },
                "required": ["repository", "run"],
            },
            handler=jobs,
        )
    )
    server.register(
        Tool(
            name="pull_requests",
            description="Pull requests, most recently updated first. `state` is not defaulted.",
            schema={
                "type": "object",
                "properties": {
                    "repository": _REPO_ARG,
                    "state": {"type": "string", "description": "open, closed, all."},
                    "base": {"type": "string", "description": "Target branch."},
                    "per_page": _PER_PAGE_ARG,
                },
                "required": ["repository"],
            },
            handler=pull_requests,
        )
    )
    server.register(
        Tool(
            name="file_at",
            description="One file's contents at one commit, base64-encoded by GitHub.",
            schema={
                "type": "object",
                "properties": {
                    "repository": _REPO_ARG,
                    "path": {"type": "string", "description": "e.g. 'k8s/base/deploy.yaml'."},
                    "ref": {"type": "string", "description": "A sha or branch name."},
                },
                "required": ["repository", "path", "ref"],
            },
            handler=file_at,
        )
    )
    server.register(
        Tool(
            name="diff",
            description="Files changed in one pull request, with per-file patches.",
            schema={
                "type": "object",
                "properties": {
                    "repository": _REPO_ARG,
                    "pull_request": {"type": "integer", "description": "PR number."},
                    "per_page": _PER_PAGE_ARG,
                },
                "required": ["repository", "pull_request"],
            },
            handler=diff,
        )
    )
    return server
