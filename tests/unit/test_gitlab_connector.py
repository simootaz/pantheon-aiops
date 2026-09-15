"""The GitLab connector: what it may reach, and what it must never put in a URL.

Two properties carry this file. A credential in a query string is in the reverse
proxy's access log and in the browser history of whoever pasted it, so the token
travels in a header. And a project reference goes into a path segment, so it is
validated before substitution rather than escaped afterwards - the same lesson
`connectors/loki/tools.py` records about label names.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from connectors._base.python.base_server import ToolError
from connectors.gitlab import tools
from core.config import get_settings

PROJECT = "group/checkout"
ENCODED = "group%2Fcheckout"


class _Recorder:
    """A transport that records the request and answers with a fixture."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = body if body is not None else {"id": 42}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "nothing was requested"
        return self.requests[-1]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Recorder]:
    """Intercepts at the transport, so the real client code runs.

    Patching `_get` would test the callers and skip the allowlist, the headers
    and the status handling - which is where everything interesting is.
    """
    recording = _Recorder()
    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(recording)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    yield recording


@pytest.fixture
def with_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    token = "glpat-not-a-real-token"
    monkeypatch.setenv("GITLAB_TOKEN", token)
    get_settings.cache_clear()
    yield token
    get_settings.cache_clear()


def _answering(status: int, body: Any = None) -> Any:
    """A patched AsyncClient that answers with one fixed response.

    The real class is captured BEFORE the patch. `tools.httpx` is the global
    httpx module, so a lambda calling `httpx.AsyncClient` inside the patch calls
    the patch - which passes `transport` twice and fails with a TypeError that
    reads as a broken test rather than as a recursive fixture.
    """
    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(status, json=body or {})
        )
        return real_client(**kwargs)

    return _client


# --- the token never reaches the URL -------------------------------------------------


@pytest.mark.asyncio
async def test_the_token_travels_in_a_header(recorder: _Recorder, with_token: str) -> None:
    """GitLab accepts `?private_token=` and it works. It is also a credential in
    a query string, which lands in the reverse proxy's access log and in the
    history of whoever pasted the URL."""
    await tools.pipeline({"project": PROJECT, "pipeline": 7})

    request = recorder.last
    assert request.headers.get("PRIVATE-TOKEN") == with_token
    assert with_token not in str(request.url), "the credential is in the URL"


@pytest.mark.asyncio
async def test_no_token_is_not_an_error(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitLab serves public projects unauthenticated. Refusing to start without
    a token would make a public read impossible in order to prevent a private
    read GitLab already refuses on its own."""
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        await tools.pipeline({"project": PROJECT, "pipeline": 7})

        assert "PRIVATE-TOKEN" not in recorder.last.headers
    finally:
        get_settings.cache_clear()


# --- the project reference is validated before it is substituted ------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../admin",
        "group/checkout/../../other",
        "group checkout",
        "",
        "/leading-slash",
        "group/checkout?private_token=stolen",
    ],
)
def test_a_project_reference_that_could_escape_its_segment_is_refused(hostile: str) -> None:
    """A value checked once it is already inside a URL is a value checked too
    late."""
    with pytest.raises(ToolError, match="not a GitLab project reference"):
        tools._project_path(hostile)


def test_a_real_project_path_is_encoded_rather_than_passed_through() -> None:
    """`quote(safe="")` is what turns `group/project` into `group%2Fproject`.
    Without the empty `safe` the slash survives and addresses a different
    endpoint - which returns a plausible answer, and that is the failure that
    does not look like one."""
    assert tools._project_path(PROJECT) == ENCODED
    assert tools._project_path("1234") == "1234"


@pytest.mark.asyncio
async def test_an_encoded_project_path_is_inside_the_allowlist(recorder: _Recorder) -> None:
    """The encoding and the allowlist have to agree. A path that validates and
    is then refused would be a connector that cannot reach its own endpoints."""
    await tools.pipeline({"project": PROJECT, "pipeline": 7})

    assert ENCODED in str(recorder.last.url)


@pytest.mark.parametrize("field", ["pipeline", "merge_request"])
def test_a_non_numeric_id_is_refused(field: str) -> None:
    with pytest.raises(ToolError, match="must be a number"):
        tools._numeric("7; DROP", what=field)


# --- read-only ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_path_outside_the_allowlist_is_refused() -> None:
    """GitLab's pipeline-trigger and branch-delete endpoints are deliberately
    unreachable. A denylist would have to know today about the endpoint added in
    the next release."""
    with pytest.raises(ToolError, match="not one of this connector's read paths"):
        await tools._get("/api/v4/projects/1/repository/branches/main")


@pytest.mark.asyncio
async def test_the_trigger_endpoint_is_refused_even_though_it_looks_like_a_read() -> None:
    """`/pipeline` singular triggers a run; `/pipelines/7` reads one. One
    character apart, and the allowlist is what tells them apart."""
    with pytest.raises(ToolError, match="not one of this connector's read paths"):
        await tools._get("/api/v4/projects/1/pipeline")


def test_the_allowlist_admits_exactly_the_four_shapes() -> None:
    """Both directions. An allowlist that admitted nothing would pass every
    refusal test above."""
    assert tools._allowed(f"/api/v4/projects/{ENCODED}/pipelines/7")
    assert tools._allowed(f"/api/v4/projects/{ENCODED}/pipelines/7/jobs")
    assert tools._allowed(f"/api/v4/projects/{ENCODED}/merge_requests")
    assert tools._allowed(f"/api/v4/projects/{ENCODED}/merge_requests/12/changes")

    assert not tools._allowed(f"/api/v4/projects/{ENCODED}/pipelines/7/jobs/1/artifacts")
    assert not tools._allowed(f"/api/v4/projects/{ENCODED}/merge_requests/12/merge")


# --- failures say which failure ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rejected_credential_is_not_reported_as_an_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller reading 401 as "no pipelines" would report a healthy pipeline
    history for a project it cannot see."""
    monkeypatch.setattr(httpx, "AsyncClient", _answering(401))

    with pytest.raises(ToolError, match="rejected the credential"):
        await tools.pipeline({"project": PROJECT, "pipeline": 7})


@pytest.mark.asyncio
async def test_a_404_says_it_may_be_permissions_rather_than_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitLab answers 404 for a project a token cannot see as well as for one
    that does not exist - deliberately, because existence is itself a
    disclosure. Reporting only "not found" sends whoever is debugging to check
    the id when the fix is a scope."""
    monkeypatch.setattr(httpx, "AsyncClient", _answering(404))

    with pytest.raises(ToolError, match="missing scope"):
        await tools.pipeline({"project": PROJECT, "pipeline": 7})


@pytest.mark.asyncio
async def test_an_unreachable_gitlab_names_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(_explode)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)

    with pytest.raises(ToolError, match="is unreachable"):
        await tools.pipeline({"project": PROJECT, "pipeline": 7})


# --- the tools themselves --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_requests_does_not_default_its_state(recorder: _Recorder) -> None:
    """DORA lead time needs merged ones and a review-latency question needs open
    ones. A default here would be one of those silently answering the other."""
    await tools.merge_requests({"project": PROJECT})

    assert "state" not in recorder.last.url.params


@pytest.mark.asyncio
async def test_merge_requests_passes_the_state_it_was_given(recorder: _Recorder) -> None:
    await tools.merge_requests({"project": PROJECT, "state": "merged"})

    assert recorder.last.url.params["state"] == "merged"


@pytest.mark.asyncio
async def test_an_oversized_page_is_refused_with_the_cap_named(recorder: _Recorder) -> None:
    """GitLab silently clamps it, and a clamped list of merge requests looks
    like a quiet week rather than a truncated answer."""
    with pytest.raises(ToolError, match="cap of 100"):
        await tools.merge_requests({"project": PROJECT, "per_page": 500})


@pytest.mark.asyncio
async def test_the_diff_reaches_the_changes_endpoint(recorder: _Recorder) -> None:
    await tools.diff({"project": PROJECT, "merge_request": 12})

    assert str(recorder.last.url).endswith(f"/projects/{ENCODED}/merge_requests/12/changes")


def test_every_declared_tool_has_a_handler_and_a_schema() -> None:
    server = tools.build_server()

    assert set(server.tools) == {"pipeline", "jobs", "merge_requests", "diff"}
    assert server.read_only, "the GitLab connector must expose no mutating tool"
