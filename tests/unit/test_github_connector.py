"""The GitHub connector: what it may reach, and which 403 it is looking at.

The property that carries this file: GitHub answers 403 for a rate limit AND for
a missing scope, and they are fixed differently - one by waiting, one by fixing a
token. Reporting both as "forbidden" sends whoever is on call to check a
credential that is fine, which is the most expensive kind of wrong error message:
confident, specific, and about the wrong system.

`owner/repo` is two real path segments here, unlike GitLab's encoded single one.
Encoding the slash would address an endpoint that does not exist, so the rule is
the opposite of the GitLab connector's - and for the same underlying reason: the
check has to match how the API actually addresses things.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from connectors._base.python.base_server import ToolError
from connectors.github import tools
from core.config import get_settings

REPO = "acme/checkout"


class _Recorder:
    """A transport that records the request and answers with a fixture."""

    def __init__(self, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self.requests: list[httpx.Request] = []

    body: Any = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self.status,
            json=self.body if self.body is not None else {"id": 42},
            headers=self.headers,
        )

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "nothing was requested"
        return self.requests[-1]


def _patch_body(recording: _Recorder, body: Any) -> None:
    """What this recorder answers with. Set per test, because `file_at` cares
    about the shape of the body and every other tool does not."""
    recording.body = body


def _patch(monkeypatch: pytest.MonkeyPatch, recording: _Recorder) -> None:
    """Intercept at the transport, so the real client code runs.

    The real class is captured BEFORE the patch. A lambda calling
    `httpx.AsyncClient` inside the patch calls the patch - which passes
    `transport` twice and fails with a TypeError that reads as a broken test
    rather than as a recursive fixture. That cost a round on the GitLab file.
    """
    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(recording)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Recorder]:
    recording = _Recorder()
    _patch(monkeypatch, recording)
    yield recording


@pytest.fixture
def with_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    token = "ghp-not-a-real-token"
    monkeypatch.setenv("GITHUB_TOKEN", token)
    get_settings.cache_clear()
    yield token
    get_settings.cache_clear()


# --- which 403 is this ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rate_limit_is_not_reported_as_a_credential_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distinction this connector exists to make. Both are 403, and
    reporting a rate limit as "check your token" sends somebody to fix a
    credential that is fine."""
    _patch(
        monkeypatch,
        _Recorder(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1756650000"}),
    )

    with pytest.raises(ToolError, match="rate-limited") as refused:
        await tools.actions_run({"repository": REPO, "run": 7})

    assert "1756650000" in str(refused.value), "the reset time is what makes it actionable"
    assert "not a credential problem" in str(refused.value)


@pytest.mark.asyncio
async def test_a_403_with_quota_left_is_reported_as_a_scope_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction. A connector that called every 403 a rate limit
    would pass the test above and be exactly as wrong."""
    _patch(monkeypatch, _Recorder(403, {"X-RateLimit-Remaining": "4998"}))

    with pytest.raises(ToolError, match="lacks a scope"):
        await tools.actions_run({"repository": REPO, "run": 7})


@pytest.mark.asyncio
async def test_a_403_with_no_rate_limit_headers_at_all_is_a_scope_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy that strips the headers must not turn a scope error into a rate
    limit - the safe reading of an absent count is "not a rate limit", because
    telling somebody to wait for a quota that will never reset is a dead end."""
    _patch(monkeypatch, _Recorder(403, {}))

    with pytest.raises(ToolError, match="lacks a scope"):
        await tools.actions_run({"repository": REPO, "run": 7})


@pytest.mark.asyncio
async def test_a_401_is_not_reported_as_an_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller reading 401 as "no runs" would report a healthy pipeline
    history for a repository it cannot see."""
    _patch(monkeypatch, _Recorder(401))

    with pytest.raises(ToolError, match="rejected the credential"):
        await tools.actions_run({"repository": REPO, "run": 7})


@pytest.mark.asyncio
async def test_a_404_says_it_may_be_permissions_rather_than_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub answers 404 for a private repository a token cannot see as well
    as for one that does not exist - deliberately, because existence is itself
    a disclosure. Reporting only "not found" sends whoever is debugging to
    check the name when the fix is a scope."""
    _patch(monkeypatch, _Recorder(404))

    with pytest.raises(ToolError, match="missing scope"):
        await tools.actions_run({"repository": REPO, "run": 7})


# --- the credential and the version travel in headers ------------------------------------


@pytest.mark.asyncio
async def test_the_token_travels_in_a_header_and_never_the_url(
    recorder: _Recorder, with_token: str
) -> None:
    await tools.actions_run({"repository": REPO, "run": 7})

    request = recorder.last
    assert request.headers.get("Authorization") == f"Bearer {with_token}"
    assert with_token not in str(request.url), "the credential is in the URL"


@pytest.mark.asyncio
async def test_the_api_version_is_pinned(recorder: _Recorder) -> None:
    """Unset, a request gets whatever the current default is - so a response
    shape can change under a running deployment without anything in this
    repository changing, and it arrives as a parse error months later."""
    await tools.actions_run({"repository": REPO, "run": 7})

    assert recorder.last.headers.get("X-GitHub-Api-Version") == tools.API_VERSION


@pytest.mark.asyncio
async def test_no_token_is_not_an_error(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub serves public repositories unauthenticated at a lower rate limit.
    Refusing to start without a token would make a public read impossible in
    order to prevent a private read GitHub already refuses on its own."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        await tools.actions_run({"repository": REPO, "run": 7})

        assert "Authorization" not in recorder.last.headers
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_the_host_comes_from_configuration(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An endpoint written into a connector cannot be pointed at GitHub
    Enterprise without a release. The centralised-config guard caught this
    hardcoded and was right to."""
    monkeypatch.setenv("GITHUB_API_URL", "https://github.acme.internal/api/v3")
    get_settings.cache_clear()
    try:
        await tools.actions_run({"repository": REPO, "run": 7})

        assert str(recorder.last.url).startswith("https://github.acme.internal/api/v3/repos/")
    finally:
        get_settings.cache_clear()


# --- owner/repo is two segments, and stays two ---------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "acme",
        "acme/checkout/extra",
        "../../admin/repo",
        "acme/../other",
        "acme/checkout?token=stolen",
        "acme /checkout",
        "",
        "/checkout",
    ],
)
def test_a_repository_that_is_not_exactly_owner_slash_repo_is_refused(hostile: str) -> None:
    """A second slash adds a path segment, and a value checked once it is
    already inside a URL is a value checked too late."""
    with pytest.raises(ToolError, match="not a GitHub repository"):
        tools._repo_path(hostile)


def test_a_real_repository_keeps_its_slash() -> None:
    """The opposite of the GitLab rule, deliberately. GitHub's path really is
    two segments, so encoding the slash would address an endpoint that does not
    exist."""
    assert tools._repo_path(REPO) == "acme/checkout"
    assert "%2F" not in tools._repo_path(REPO)


@pytest.mark.parametrize("field", ["run", "pull_request"])
def test_a_non_numeric_id_is_refused(field: str) -> None:
    with pytest.raises(ToolError, match="must be a number"):
        tools._numeric("7; DROP", what=field)


# --- read-only ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_path_outside_the_allowlist_is_refused() -> None:
    """GitHub's merge, branch-delete and workflow-rerun endpoints are
    deliberately unreachable."""
    with pytest.raises(ToolError, match="not one of this connector's read paths"):
        await tools._get(f"/repos/{REPO}/git/refs/heads/main")


@pytest.mark.asyncio
async def test_the_rerun_endpoint_is_refused_though_it_sits_under_a_read_path() -> None:
    """`/actions/runs/7` reads; `/actions/runs/7/rerun` spends money. The
    allowlist is what tells them apart, and a prefix match would not."""
    with pytest.raises(ToolError, match="not one of this connector's read paths"):
        await tools._get(f"/repos/{REPO}/actions/runs/7/rerun")


@pytest.mark.asyncio
async def test_the_merge_endpoint_is_refused() -> None:
    with pytest.raises(ToolError, match="not one of this connector's read paths"):
        await tools._get(f"/repos/{REPO}/pulls/12/merge")


def test_the_allowlist_admits_exactly_the_four_shapes() -> None:
    """Both directions. An allowlist that admitted nothing would pass every
    refusal test above."""
    assert tools._allowed(f"/repos/{REPO}/actions/runs/7")
    assert tools._allowed(f"/repos/{REPO}/actions/runs/7/jobs")
    assert tools._allowed(f"/repos/{REPO}/pulls")
    assert tools._allowed(f"/repos/{REPO}/pulls/12/files")


# --- the tools themselves ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_requests_does_not_default_its_state(recorder: _Recorder) -> None:
    """GitHub's own default is `open`, which silently answers a lead-time
    question - which needs closed ones - with the wrong set entirely."""
    await tools.pull_requests({"repository": REPO})

    assert "state" not in recorder.last.url.params


@pytest.mark.asyncio
async def test_pull_requests_passes_the_state_it_was_given(recorder: _Recorder) -> None:
    await tools.pull_requests({"repository": REPO, "state": "closed"})

    assert recorder.last.url.params["state"] == "closed"


@pytest.mark.asyncio
async def test_an_oversized_page_is_refused_with_the_cap_named(recorder: _Recorder) -> None:
    """GitHub silently clamps it, and a clamped list of pull requests looks
    like a quiet week rather than a truncated answer."""
    with pytest.raises(ToolError, match="cap of 100"):
        await tools.pull_requests({"repository": REPO, "per_page": 500})


@pytest.mark.asyncio
async def test_the_diff_reaches_the_files_endpoint(recorder: _Recorder) -> None:
    await tools.diff({"repository": REPO, "pull_request": 12})

    assert str(recorder.last.url).split("?")[0].endswith(f"/repos/{REPO}/pulls/12/files")


@pytest.mark.asyncio
async def test_an_unreachable_github_names_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(_explode)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    with pytest.raises(ToolError, match="is unreachable"):
        await tools.actions_run({"repository": REPO, "run": 7})


def test_every_declared_tool_has_a_handler_and_a_schema() -> None:
    server = tools.build_server()

    assert set(server.tools) == {"actions_run", "jobs", "pull_requests", "diff", "file_at"}
    assert server.read_only, "the GitHub connector must expose no mutating tool"


# --- file_at: the bytes, not a reconstruction ------------------------------------------


@pytest.mark.asyncio
async def test_a_file_is_fetched_at_the_ref_it_was_asked_for(recorder: _Recorder) -> None:
    """Two reads at two shas yield the real bytes. GitHub omits `patch` for a
    file above roughly 20k of diff, so a reviewer built on patches would
    silently skip the large manifest changes most worth reviewing."""
    _patch_body(recorder, {"encoding": "base64", "content": "eA=="})

    await tools.file_at({"repository": REPO, "path": "k8s/base/deploy.yaml", "ref": "abc123"})

    url = recorder.last.url
    assert str(url).split("?")[0].endswith(f"/repos/{REPO}/contents/k8s/base/deploy.yaml")
    assert url.params["ref"] == "abc123"


@pytest.mark.parametrize(
    "hostile",
    ["/etc/passwd", "../../../etc/passwd", "k8s/../../secrets.yaml", "k8s/..", "", "a b.yaml"],
)
def test_a_path_that_could_leave_the_repository_is_refused(hostile: str) -> None:
    """An allowlist of characters rather than a denylist of dangerous ones - a
    denylist has to know today about the character that matters tomorrow."""
    with pytest.raises(ToolError, match="not a path inside a repository"):
        tools._repo_file(hostile)


def test_a_real_nested_path_is_kept_whole() -> None:
    """Slashes are legitimate here: `/contents/k8s/base/x.yaml` is how the
    endpoint is addressed, so encoding them would name a file that does not
    exist."""
    assert tools._repo_file("k8s/base/deployment.yaml") == "k8s/base/deployment.yaml"


@pytest.mark.asyncio
async def test_a_directory_listing_is_refused_rather_than_reviewed(recorder: _Recorder) -> None:
    """GitHub answers a list for a directory. Reviewed as a manifest it parses
    as nothing and reports a clean change."""
    _patch_body(recorder, [{"name": "deploy.yaml"}])

    with pytest.raises(ToolError, match="is a directory"):
        await tools.file_at({"repository": REPO, "path": "k8s", "ref": "abc123"})


@pytest.mark.asyncio
async def test_a_file_too_large_for_the_contents_api_is_refused(recorder: _Recorder) -> None:
    """Files over 1MB are served through the blobs API instead, and an empty
    body reviewed as a manifest reads as "everything was removed"."""
    _patch_body(recorder, {"encoding": "none", "content": ""})

    with pytest.raises(ToolError, match="no content"):
        await tools.file_at({"repository": REPO, "path": "k8s/big.yaml", "ref": "abc123"})


@pytest.mark.asyncio
async def test_the_contents_path_is_inside_the_allowlist() -> None:
    assert tools._allowed(f"/repos/{REPO}/contents/k8s/base/deploy.yaml")
    assert not tools._allowed(f"/repos/{REPO}/contents")
