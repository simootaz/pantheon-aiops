"""The app around the routers: shutdown, correlation, and what an error body says.

Two of these are about things that only go wrong later. A pool that is never
returned presents as the database being down; a validation error that echoes
the submitted body presents as nothing at all until the day somebody POSTs a
credential into it.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import INVESTIGATION_HEADER, _correlate, create_app
from core.cerberus.redaction import PLACEHOLDER, REDEEMED
from core.observability.logging import _INVESTIGATION
from core.store.investigations import InMemoryInvestigationStore
from core.store.providers import InMemoryProviderStore

SECRET = "postgres://user:hunter2@db:5432/prod"


class _ClosingStore(InMemoryInvestigationStore):
    """A store that records whether it was given back."""

    def __init__(self) -> None:
        super().__init__()
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


class _RefusingStore(InMemoryProviderStore):
    """One that fails on the way out, to prove the other still closes."""

    def __init__(self) -> None:
        super().__init__(master=b"0" * 32)

    async def close(self) -> None:
        raise RuntimeError("the pool is already gone")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )
    with TestClient(app) as test_client:
        yield test_client


# --- shutdown gives the pools back ------------------------------------------------------


def test_the_stores_are_closed_on_shutdown() -> None:
    """A pool created lazily and held for the life of the process leaks one per
    reload in development, until Postgres refuses connections - and that
    presents as the database being down."""
    store = _ClosingStore()
    app = create_app(
        investigation_store=store,
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )

    with TestClient(app):
        assert store.closed == 0

    assert store.closed == 1


def test_one_store_failing_to_close_does_not_strand_the_other() -> None:
    """A shutdown path that stops at the first error is a shutdown path that
    does not run."""
    store = _ClosingStore()
    app = create_app(investigation_store=store, provider_store=_RefusingStore())

    with TestClient(app):
        pass

    assert store.closed == 1


def test_a_store_with_nothing_to_close_is_not_a_failure() -> None:
    """The in-memory stores have no `close`, and a shutdown that raised on one
    would make every test using them fail at teardown."""
    app = create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# --- correlation ---------------------------------------------------------------------------


class _FakeRequest:
    """The one thing `_correlate` reads.

    A stand-in rather than a real `Request`, because building one needs an ASGI
    scope and a receive channel to assert on a header lookup. The `type: ignore`
    at each call site is the cost of that, and it is cheaper than a fixture
    whose setup is longer than the thing under test.
    """

    def __init__(self, header: str | None) -> None:
        self.headers = {INVESTIGATION_HEADER: header} if header is not None else {}


async def _seen(request: Any) -> Any:
    """A `call_next` that records the tag as the handler would see it."""
    _seen.tag = _INVESTIGATION.get()  # type: ignore[attr-defined]
    return "response"


@pytest.mark.asyncio
async def test_the_tag_is_set_while_the_handler_runs() -> None:
    """Tested against `_correlate` directly rather than through TestClient.

    Through the client this is unobservable: each request runs in its own task
    with its own contextvar copy, so an assertion made outside the request sees
    `None` whatever the middleware did. Two plants passed that way - an empty
    header tagging every line, and a `set()` with no reset - because the fixture
    could not see the thing it claimed to check.
    """
    await _correlate(_FakeRequest("run-42"), _seen)  # type: ignore[arg-type]

    assert _seen.tag == "run-42"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_the_tag_is_cleared_on_the_way_out() -> None:
    """A leaked tag attributes the next work in this task to the previous run,
    which is worse than no correlation at all: absent correlation is visibly
    absent, wrong correlation is not."""
    await _correlate(_FakeRequest("run-42"), _seen)  # type: ignore[arg-type]

    assert _INVESTIGATION.get() is None


@pytest.mark.asyncio
async def test_the_tag_is_cleared_even_when_the_handler_raises() -> None:
    """Which is why it is a context manager and not a setter. The handler that
    raises is exactly the one whose lines somebody will go looking for."""

    async def _explodes(request: Any) -> Any:
        raise RuntimeError("the handler failed")

    with pytest.raises(RuntimeError):
        await _correlate(_FakeRequest("run-42"), _explodes)  # type: ignore[arg-type]

    assert _INVESTIGATION.get() is None


@pytest.mark.asyncio
async def test_an_empty_header_is_treated_as_absent() -> None:
    """Tagging every line with the empty string would be worse than not
    tagging: a field that is present and meaningless survives every filter
    somebody writes to find the ones that are missing."""
    await _correlate(_FakeRequest(""), _seen)  # type: ignore[arg-type]

    assert _seen.tag is None  # type: ignore[attr-defined]


def test_a_request_carrying_an_investigation_id_is_accepted(client: TestClient) -> None:
    """The id is READ, not generated. One this process invented would correlate
    the API's own lines and nothing else - the agents, connectors and worker are
    where an incident is reconstructed, and they only share an id somebody
    passed in.

    End to end, so the middleware is actually installed. What it does once
    installed is asserted above, where it can be seen.
    """
    response = client.get("/health", headers={INVESTIGATION_HEADER: str(uuid4())})

    assert response.status_code == 200


# --- a validation error must not hand the input back ------------------------------------------


def test_a_credential_in_a_malformed_body_is_not_echoed(client: TestClient) -> None:
    """FastAPI's default handler echoes the offending input so a caller can see
    what was wrong with it. That is right, and it is a leak path: the value
    returns in the error, into whatever logs the response, and into the
    caller's terminal history.
    """
    REDEEMED.clear()
    REDEEMED.register(SECRET)
    try:
        # POST /providers, because that payload legitimately carries an api_key
        # and needs no token - so validation actually runs. An authenticated
        # endpoint would 401 first and the body would never be echoed, which
        # makes the test pass without exercising anything.
        response = client.post(
            "/providers",
            json={"base_url": "https://api.example.com/v1", "api_key": SECRET},
        )

        assert response.status_code == 422, (
            "the fixture must actually fail validation, or nothing is echoed to redact"
        )
        body = response.text
        assert SECRET not in body, "the submitted credential came back in the error"
        assert "hunter2" not in body
    finally:
        REDEEMED.clear()


def test_a_validation_error_still_says_what_was_wrong(client: TestClient) -> None:
    """The control. Dropping the input entirely would make every validation
    failure unactionable to fix the one case in a thousand that carries a
    secret - and a 422 nobody can act on is a 422 people stop reading.
    """
    response = client.post("/providers", json={"base_url": "https://api.example.com/v1"})

    assert response.status_code == 422
    detail: Any = json.loads(response.text)
    assert detail, "the error body carries nothing at all"
    assert PLACEHOLDER not in json.dumps(detail), (
        "nothing in this payload is a secret, so nothing should have been redacted"
    )
