"""Liveness, readiness and build-info endpoints.

Only liveness exists today. Readiness needs datastore and connector checks,
which arrive with the components they check.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from fastapi import APIRouter

from api import __version__
from api.schemas.common import HealthResponse

SERVICE_NAME = "pantheon-api"

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Report that the process is up. Does not touch any dependency."""
    return HealthResponse(service=SERVICE_NAME, version=__version__)


# TODO: Phase 1 - add /ready (datastore + connector reachability) and /build-info
