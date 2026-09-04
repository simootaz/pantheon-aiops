"""The agents roster, readiness and build-info.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.routers import health as health_module
from core.orchestrator import dispatcher
from core.registry import loader
from core.store.investigations import InMemoryInvestigationStore


class _Probe:
    """A stand-in for the Prometheus readiness call.

    Unit tests must not open sockets. The stack is not guaranteed to be up, and
    on this platform a closed loopback port does not refuse promptly - so a real
    call here fails by hanging rather than by erroring, which is the worst shape
    a test failure can take.
    """

    def __init__(self, status_code: int = 200, error: Exception | None = None) -> None:
        self.status_code = status_code
        self.error = error

    async def __aenter__(self) -> _Probe:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, _url: str) -> _Probe:
        if self.error is not None:
            raise self.error
        return self

    def raise_for_status(self) -> None:
        # A plain error, not an HTTPStatusError: constructing one needs a real
        # request and response object, and the code under test only cares that
        # something was raised.
        if self.status_code >= 400:
            raise RuntimeError(f"prometheus answered {self.status_code}")


def _stub_httpx(monkeypatch: pytest.MonkeyPatch, probe: _Probe) -> None:
    """Replace health's *reference* to httpx, not httpx itself.

    Setting `AsyncClient` on the httpx module mutates it for every importer -
    and `mcp` uses `httpx.AsyncClient` inside a type annotation, so a lambda
    there turns an unrelated library's `X | None` into a TypeError at import.
    Patching the name where it is used keeps the blast radius to this module.
    """
    monkeypatch.setattr(
        health_module,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **_: probe, HTTPStatusError=httpx.HTTPStatusError),
    )


@pytest.fixture
def prometheus_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_httpx(monkeypatch, _Probe())


class _RecordingStore:
    """A working store that remembers which methods readiness called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def save(self, investigation: Any) -> None:
        self.calls.append("save")

    async def get(self, investigation_id: Any) -> Any:
        self.calls.append("get")
        return None

    async def recent(self, limit: int = 20, *, tenant: str | None = None) -> list[Any]:
        self.calls.append("recent")
        return []


class _BrokenStore:
    """A store whose reads fail, for the unready case."""

    async def save(self, investigation: Any) -> None:  # pragma: no cover - never called
        raise AssertionError("readiness must not write")

    async def get(self, investigation_id: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("readiness must not fetch by id")

    async def recent(self, limit: int = 20, *, tenant: str | None = None) -> list[Any]:
        raise ConnectionRefusedError("the database is not there")


@pytest.fixture
def client(prometheus_up: None) -> Iterator[TestClient]:
    with TestClient(create_app(investigation_store=InMemoryInvestigationStore())) as test_client:
        yield test_client


# --- the roster --------------------------------------------------------------


def test_every_rostered_agent_is_listed(client: TestClient) -> None:
    rows = client.get("/agents").json()
    assert {row["codename"] for row in rows} == set(loader.load_all())
    assert [row["codename"] for row in rows] == sorted(row["codename"] for row in rows)


def test_the_roster_says_which_agents_actually_run(client: TestClient) -> None:
    """The load-bearing field.

    Ten manifests validate and one agent has an implementation. A listing
    without this would report ten working agents, which is the most misleading
    thing this API could say - and it is exactly the distinction `PlanStep`
    draws between COMPLETE and SKIPPED.
    """
    rows = client.get("/agents").json()
    implemented = {row["codename"] for row in rows if row["implemented"]}

    assert implemented == set(dispatcher.AGENTS), (
        "the roster's `implemented` disagrees with the dispatcher's registry, so "
        "the API is reporting an intention as a capability"
    )
    assert implemented, "no agent is implemented; the app factory did not register one"
    assert len(implemented) < len(rows), (
        "every agent reports as implemented - either they all are, or this field "
        "has stopped being read from the registry"
    )


def test_one_manifest_comes_back_whole(client: TestClient) -> None:
    """Summarising it would drop the two things someone comes here to check."""
    body = client.get("/agents/argus").json()
    assert body["codename"] == "argus"
    assert body["tools"], "the tool allowlist is missing from the manifest response"
    assert body["budget"]["max_tool_calls"] >= 1, "the budget is missing"


def test_an_unknown_agent_is_a_404_naming_the_roster(client: TestClient) -> None:
    response = client.get("/agents/gilgamesh")
    assert response.status_code == 404
    assert "argus" in response.json()["detail"], (
        "a 404 that does not say what does exist costs the reader another request"
    )


# --- build info ---------------------------------------------------------------


def test_build_info_reports_what_is_running(client: TestClient) -> None:
    """Asked after an incident, when memory of the deploy is not evidence."""
    body = client.get("/health/build-info").json()
    assert body["service"] == "pantheon-api"
    assert body["version"], "no version"
    assert body["python"].startswith("3."), body["python"]


# --- readiness ----------------------------------------------------------------


def test_liveness_does_not_consult_a_dependency(prometheus_up: None) -> None:
    """A liveness probe that reads the database restarts the process when the
    database is slow, which is the opposite of what it is for."""
    app = create_app(investigation_store=_BrokenStore())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_readiness_reports_each_dependency_separately(client: TestClient) -> None:
    body = client.get("/health/ready").json()
    assert {check["name"] for check in body["checks"]} == {"datastore", "prometheus"}


def test_a_failing_dependency_makes_the_probe_503_not_a_200_with_a_flag(
    prometheus_up: None,
) -> None:
    """The status code is the part machines read.

    A readiness endpoint returning 200 with `ready: false` is treated as ready
    by most orchestrators, and the pod keeps taking traffic it cannot serve.
    """
    app = create_app(investigation_store=_BrokenStore())
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["ready"] is False

    datastore = next(check for check in body["checks"] if check["name"] == "datastore")
    assert datastore["ready"] is False
    assert "ConnectionRefusedError" in datastore["detail"], (
        f"a failing check that does not say why: {datastore['detail']!r}"
    )


def test_a_failing_dependency_does_not_hide_the_ones_that_answered(
    prometheus_up: None,
) -> None:
    """Every check runs. Short-circuiting on the first failure means a reader
    fixes one dependency and discovers the next one only on the retry."""
    app = create_app(investigation_store=_BrokenStore())
    with TestClient(app) as client:
        checks = client.get("/health/ready").json()["checks"]

    assert len(checks) == 2, f"a failing datastore suppressed the other check: {checks}"


def test_readiness_never_writes(prometheus_up: None) -> None:
    """A probe with a side effect is a probe that fills a table.

    Asserted on a recorded call list rather than on a stub that raises. Relying
    on the raise would leave this test with no assertion of its own - and
    `test_every_test_asserts_something` catches exactly that, correctly: a
    reader cannot tell a test that checks nothing from one whose check lives
    somewhere else.
    """
    store = _RecordingStore()
    app = create_app(investigation_store=store)
    with TestClient(app) as probe_client:
        probe_client.get("/health/ready")
        probe_client.get("/health/ready")

    assert store.calls == ["recent", "recent"], (
        f"readiness touched the store in ways it should not: {store.calls}"
    )


def test_an_unreachable_prometheus_is_reported_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The connector every implemented agent depends on, when it is not there.

    Reported as a failed check, not raised: a readiness endpoint that 500s tells
    an orchestrator the process is broken, when what is broken is something it
    talks to.
    """
    _stub_httpx(monkeypatch, _Probe(error=httpx.ConnectError("no route")))
    app = create_app(investigation_store=InMemoryInvestigationStore())
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    prometheus = next(check for check in response.json()["checks"] if check["name"] == "prometheus")
    assert prometheus["ready"] is False
    assert "ConnectError" in prometheus["detail"]


def test_a_prometheus_that_answers_unhealthily_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 503 from the dependency is not the same as a reply, and must not read as one."""
    _stub_httpx(monkeypatch, _Probe(status_code=503))
    app = create_app(investigation_store=InMemoryInvestigationStore())
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 503
