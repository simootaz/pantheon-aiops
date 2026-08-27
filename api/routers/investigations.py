"""Investigation read endpoints: list and fetch.

Read-only, deliberately. Creation happens through a trigger - an alert, a
webhook, a scheduled sweep - and an endpoint that mints an Investigation from a
POST would be a second way in with none of the classification a trigger carries.
`POST /investigations` arrives when there is a human-question trigger to give it
a shape.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.contracts.investigation import Investigation
from core.store.investigations import InvestigationStore

router = APIRouter(prefix="/investigations", tags=["investigations"])


def get_store(request: Request) -> InvestigationStore:
    """The store, from application state, so tests can substitute one."""
    store: InvestigationStore | None = getattr(request.app.state, "investigation_store", None)
    if store is None:  # pragma: no cover - the app factory always sets it
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="investigation store is not configured",
        )
    return store


@router.get("", response_model=list[Investigation], summary="Recent investigations")
async def list_investigations(
    store: Annotated[InvestigationStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Investigation]:
    """Newest first."""
    return await store.recent(limit)


@router.get(
    "/{investigation_id}",
    response_model=Investigation,
    summary="One investigation, whole",
)
async def get_investigation(
    investigation_id: UUID,
    store: Annotated[InvestigationStore, Depends(get_store)],
) -> Investigation:
    """The Investigation, including its plan, findings and verdict.

    404 when it does not exist, which includes the window between an alert being
    accepted and Zeus writing the first row. The receiver returns 202 and an id;
    a reader that polls will see 404 and then the run.
    """
    investigation = await store.get(investigation_id)
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation {investigation_id}",
        )
    return investigation
