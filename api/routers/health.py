"""Liveness, readiness and build-info endpoints.

LIVENESS AND READINESS ANSWER DIFFERENT QUESTIONS
--------------------------------------------------
`/health` says the process is up. It touches nothing, because a liveness probe
that consults a database restarts the process when the database is slow - which
is the opposite of what it is for.

`/health/ready` says the process can do its job, which means asking the things
it depends on. A pod failing readiness is taken out of rotation; a pod failing
liveness is killed. Collapsing them turns a transient dependency blip into a
restart loop.

READINESS RETURNS ITS CHECKS, NOT JUST ITS VERDICT
---------------------------------------------------
`ready: false` with nothing to look at is the state that costs an hour. Each
dependency reports separately, and a failing one says why - so the reader learns
"Postgres refused the connection" rather than "not ready".

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import platform
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response, status

from api import __version__
from api.schemas.common import BuildInfo, HealthResponse, ReadinessCheck, ReadinessResponse
from core.config import get_settings
from core.store.investigations import InvestigationStore

SERVICE_NAME = "pantheon-api"

#: Long enough for a healthy dependency, short enough that a readiness probe
#: does not itself become the slow thing. A probe that hangs is a probe that
#: reports nothing.
PROBE_TIMEOUT_SECONDS = 3.0

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Report that the process is up. Does not touch any dependency."""
    return HealthResponse(service=SERVICE_NAME, version=__version__)


@router.get(
    "/health/build-info",
    response_model=BuildInfo,
    summary="What is actually running",
)
async def build_info() -> BuildInfo:
    """Version and interpreter.

    Asked after an incident, when "which build was this?" is the first question
    and the answer must not depend on someone's memory of what was deployed.
    """
    return BuildInfo(
        service=SERVICE_NAME,
        version=__version__,
        python=platform.python_version(),
    )


def _store(request: Request) -> InvestigationStore | None:
    store: InvestigationStore | None = getattr(request.app.state, "investigation_store", None)
    return store


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe: can this process do its job",
)
async def ready(
    response: Response,
    store: Annotated[InvestigationStore | None, Depends(_store)],
) -> ReadinessResponse:
    """Ask every dependency, and report each answer.

    **503 when not ready**, because a readiness probe that returns 200 with
    `ready: false` in the body is a probe most orchestrators will treat as
    ready. The status code is the part that is read by machines.
    """
    checks = [await _datastore_ready(store), await _prometheus_ready()]
    everything = all(check.ready for check in checks)

    if not everything:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=everything, service=SERVICE_NAME, checks=checks)


async def _datastore_ready(store: InvestigationStore | None) -> ReadinessCheck:
    """A real query, not a connection.

    Connecting proves the socket opens. `recent` proves the schema exists and
    the credentials permit a read, which is what the process actually needs -
    and it is the check that would have caught a missing POSTGRES_PASSWORD
    rather than leaving it to the first investigation.
    """
    if store is None:  # pragma: no cover - the app factory always sets one
        return ReadinessCheck(name="datastore", ready=False, detail="no store is configured")
    try:
        await store.recent(limit=1)
    except Exception as error:
        return ReadinessCheck(
            name="datastore", ready=False, detail=f"{type(error).__name__}: {error}"[:200]
        )
    return ReadinessCheck(name="datastore", ready=True)


async def _prometheus_ready() -> ReadinessCheck:
    """The connector every implemented agent depends on.

    Only Prometheus is checked, because only Prometheus is wired. Listing
    connectors that nothing calls would report a readiness this process does not
    actually require.
    """
    url = f"{get_settings().prometheus.base}/-/ready"
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            probe = await client.get(url)
        probe.raise_for_status()
    except Exception as error:
        return ReadinessCheck(
            name="prometheus", ready=False, detail=f"{type(error).__name__}: {error}"[:200]
        )
    return ReadinessCheck(name="prometheus", ready=True)
