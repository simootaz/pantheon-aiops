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
from core.guardrails.approval_gate import ApprovalGate
from core.observability.logging import configure as configure_logging
from core.orchestrator import register_implemented
from core.store.investigations import InvestigationStore
from core.store.postgres import PostgresInvestigationStore
from core.store.postgres_providers import PostgresProviderStore
from core.store.providers import ProviderStore

TITLE = "Pantheon API"
DESCRIPTION = "Polyglot multi-agent AIOps platform."


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

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(alerts.router)
    app.include_router(investigations.router)
    app.include_router(agents.router)
    app.include_router(providers.router)
    app.include_router(approvals.router)

    return app


# TODO: Phase 3 - add lifespan (pool shutdown), middleware, and the approvals router.
# The agents router landed in Phase 1 and logging is configured above.
