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
from api.routers import health

TITLE = "Pantheon API"
DESCRIPTION = "Polyglot multi-agent AIOps platform."


def create_app() -> FastAPI:
    """Build the Pantheon API application.

    A factory rather than a module-level singleton so tests can build isolated
    instances and `uvicorn --factory` can control construction.
    """
    app = FastAPI(
        title=TITLE,
        description=DESCRIPTION,
        version=__version__,
    )

    app.include_router(health.router)

    return app


# TODO: Phase 1 - add lifespan (datastore, registry), middleware and the
# investigations, agents and approvals routers
