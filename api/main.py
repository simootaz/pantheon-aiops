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

from fastapi import FastAPI

from api import __version__
from api.routers import agents, alerts, health, investigations, webhooks
from core.bus import EventBus, InMemoryEventBus
from core.orchestrator import register_implemented
from core.store.investigations import InvestigationStore
from core.store.postgres import PostgresInvestigationStore

TITLE = "Pantheon API"
DESCRIPTION = "Polyglot multi-agent AIOps platform."


def create_app(
    *,
    event_bus: EventBus | None = None,
    investigation_store: InvestigationStore | None = None,
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
    )

    app.state.event_bus = event_bus if event_bus is not None else InMemoryEventBus()
    app.state.investigation_store = (
        investigation_store if investigation_store is not None else PostgresInvestigationStore()
    )
    # Explicit, and before any request can dispatch. A registry populated as
    # an import side effect behaves differently depending on import order.
    register_implemented()

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(alerts.router)
    app.include_router(investigations.router)
    app.include_router(agents.router)

    return app


# TODO: Phase 2 - add lifespan (pool shutdown), middleware, and the agents and
# approvals routers
