"""FastAPI application factory.

Builds the app with its middleware, routers and lifespan, and owns the OpenAPI
schema. Note that domain types are NOT generated from that schema - they come
from core/contracts/ via JSON Schema, see
docs/adr/0002-codegen-from-json-schema.md. The OpenAPI document will feed a
separate endpoint-surface generator (codegen/gen_ts_api.sh) at Phase 1.

Run with: make dev

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api import __version__
from api.routers import (
    agents,
    alerts,
    approvals,
    health,
    investigations,
    providers,
    webhooks,
)
from core.bus import EventBus, InMemoryEventBus
from core.cerberus.redaction import redact
from core.guardrails.approval_gate import ApprovalGate
from core.observability.logging import configure as configure_logging
from core.observability.logging import investigation
from core.orchestrator import register_implemented
from core.store.investigations import InvestigationStore
from core.store.postgres import PostgresInvestigationStore
from core.store.postgres_providers import PostgresProviderStore
from core.store.providers import ProviderStore

TITLE = "Pantheon API"
DESCRIPTION = "Polyglot multi-agent AIOps platform."

#: The header that ties a request's log lines to the run it belongs to.
#:
#: Read rather than generated. An id this process invented would correlate the
#: API's own lines and nothing else - the agents, the connectors and the worker
#: are where an incident is actually reconstructed, and they only share an id
#: somebody passed in.
INVESTIGATION_HEADER = "X-Investigation-Id"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start, serve, and give the pools back on the way out.

    Closing matters more than it looks. `PostgresInvestigationStore` creates a
    pool lazily and holds it for the life of the process; without this, a
    reload in development leaks one pool per restart until Postgres refuses
    connections - and that presents as the database being down.
    """
    yield

    for store in (app.state.investigation_store, app.state.provider_store):
        close = getattr(store, "close", None)
        if close is not None:
            # Each in its own try. One store failing to close must not leave the
            # other holding a pool - a shutdown path that stops at the first
            # error is a shutdown path that does not run.
            try:
                await close()
            except Exception as failure:  # pragma: no cover - shutdown is best effort
                logging.getLogger(__name__).warning(
                    "could not close %s: %s", type(store).__name__, failure
                )


async def _correlate(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Tag every log line this request emits with the investigation it belongs to.

    A context manager rather than a setter, so the tag is removed on the way out
    even when the handler raises. A leaked tag attributes the NEXT request's
    lines to the previous one, which is worse than no correlation at all -
    absent correlation is visibly absent, wrong correlation is not.
    """
    supplied = request.headers.get(INVESTIGATION_HEADER)
    if not supplied:
        return await call_next(request)
    with investigation(supplied):
        return await call_next(request)


async def _redacted_validation_error(request: Request, error: Exception) -> JSONResponse:
    """422, with the submitted input scrubbed.

    FastAPI's default handler echoes the offending input back so a caller can
    see what was wrong with it. That is the right behaviour and it is a leak
    path: a credential POSTed in a malformed body returns in the error, into
    whatever logs the response, and into the caller's terminal history.

    Redacted rather than omitted. Dropping the input entirely would make every
    validation failure unactionable to fix the one case in a thousand that
    carries a secret.
    """
    detail = error.errors() if isinstance(error, RequestValidationError) else []
    scrubbed: Any = redact(detail)
    return JSONResponse(status_code=422, content=jsonable_encoder(scrubbed))


def create_app(
    *,
    event_bus: EventBus | None = None,
    investigation_store: InvestigationStore | None = None,
    provider_store: ProviderStore | None = None,
    approval_gate: ApprovalGate | None = None,
) -> FastAPI:
    """Build the Pantheon API application.

    A factory rather than a module-level singleton so tests can build isolated
    instances and `uvicorn --factory` can control construction.

    `event_bus` is injectable for the same reason: a test that asserts an
    endpoint published something needs to hold the bus it published to. The
    default is in-memory and is replaced at Phase 2 - see core/bus.py.

    `investigation_store` defaults to Postgres, not to memory. An in-memory
    default would make every read work in development and fail the moment two
    processes existed, and the failure would look like data loss rather than a
    missing dependency.
    """
    app = FastAPI(
        title=TITLE,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )

    # Before anything can log. A handler installed later would let every line
    # emitted during construction out unredacted, and construction is where a
    # misconfigured credential is most likely to be mentioned.
    configure_logging()

    app.state.event_bus = event_bus if event_bus is not None else InMemoryEventBus()
    app.state.investigation_store = (
        investigation_store if investigation_store is not None else PostgresInvestigationStore()
    )
    # Explicit, and before any request can dispatch. A registry populated as
    # an import side effect behaves differently depending on import order.
    app.state.provider_store = (
        provider_store if provider_store is not None else PostgresProviderStore()
    )
    # One gate per process, like the capability matrix and for the same reason:
    # an approval opened by one request must be answerable by the next, and
    # there is no persistence yet. Two replicas do NOT share it - stated here
    # rather than discovered by an approval that vanishes behind a load
    # balancer.
    app.state.approval_gate = approval_gate if approval_gate is not None else ApprovalGate()

    register_implemented()

    app.middleware("http")(_correlate)
    # Overrides FastAPI's own, which echoes the submitted body unredacted.
    app.add_exception_handler(RequestValidationError, _redacted_validation_error)

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(alerts.router)
    app.include_router(investigations.router)
    app.include_router(agents.router)
    app.include_router(providers.router)
    app.include_router(approvals.router)

    return app


# The lifespan closes the pools, `_correlate` ties a request's log lines to its
# investigation, and the approvals router landed with the approval gate.
#
# What is deliberately NOT here: a middleware that authenticates. Auth is a
# per-route dependency in `api/auth/dependencies.py`, because a middleware
# guarding "everything except a list" is a list that goes stale the moment
# somebody adds a route - and it goes stale open.
