"""Approval endpoints for the human-in-the-loop gate.

The gate has held approvals since `core/guardrails/approval_gate.py` landed, and
nothing could reach it: an Action needing a person waited for one who had no way
to answer. This is that way.

THE ENDPOINT CARRIES NO DECISION AUTHORITY
--------------------------------------------
`core/contracts/ui.py` states the rule and the gate enforces it: a response
"carries no decision authority of its own; an approval reaching the Approval
Gate is re-validated there against the request it claims to answer."

So this router validates nothing about whether an approval is *allowed*. It
takes an approver and a verdict, hands them to the gate, and reports what the
gate said. Every check that matters - the request is still pending, the Action
has not changed, the approver is not the proposer - lives in one place, and
adding a second copy here is how the two drift.

WHY THE ACTION IS SENT BACK IN
--------------------------------
`POST /approvals/{id}` takes the Action body, and that is deliberate rather than
clumsy. The gate re-validates against the Action **as the caller holds it**,
because that is the object about to be executed. Looking one up from a store
instead would validate against a copy that may already have diverged from it -
which is exactly the substitution the digest exists to catch.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from core.contracts.action import Action
from core.guardrails.approval_gate import ApprovalError, ApprovalGate

router = APIRouter(prefix="/approvals", tags=["approvals"])


class Response(BaseModel):
    """A person answering one request."""

    approver: str = Field(description="Who is answering. Never the proposer.")
    approve: bool
    reason: str = Field(
        default="",
        description="Why. Optional on an approval, and the first thing read on a rejection.",
    )
    action: Action = Field(
        description=(
            "The Action as the caller holds it. Re-validated against what the "
            "approver was shown - an approval is for content, not for an id."
        )
    )


def get_gate(request: Request) -> ApprovalGate:
    gate: ApprovalGate | None = getattr(request.app.state, "approval_gate", None)
    if gate is None:  # pragma: no cover - the app factory always sets one
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="approval gate is not configured",
        )
    return gate


@router.get("", summary="Requests still waiting for a person")
async def list_pending(
    gate: Annotated[ApprovalGate, Depends(get_gate)],
) -> list[dict[str, object]]:
    """Oldest first, and expired ones are not listed.

    A queue that grows forever teaches operators to ignore it, which is the one
    outcome an approval gate cannot survive.
    """
    return [request.as_dict() for request in gate.pending()]


@router.get("/{request_id}", summary="One request and where it stands")
async def get_request(
    request_id: UUID,
    gate: Annotated[ApprovalGate, Depends(get_gate)],
) -> dict[str, object]:
    waiting = gate.get(request_id)
    if waiting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no approval request {request_id}"
        )
    return {**waiting.as_dict(), "state": gate.state(request_id).value}


@router.post("/{request_id}", summary="Approve or reject")
async def respond(
    request_id: UUID,
    response: Response,
    gate: Annotated[ApprovalGate, Depends(get_gate)],
) -> dict[str, object]:
    """Record an answer. The gate decides whether it can be honoured.

    Every refusal is a **409**, not a 400. The request is well-formed; it is the
    state that says no - already answered, expired, self-approved, or for an
    Action that has changed. A 400 would read as "fix your payload", and the fix
    is never the payload.
    """
    try:
        answered = gate.respond(
            request_id,
            response.action,
            approver=response.approver,
            approve=response.approve,
            reason=response.reason,
        )
    except ApprovalError as refused:
        message = str(refused)
        if message.startswith("no approval request"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from refused
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message) from refused

    return {**answered.as_dict(), "state": gate.state(request_id).value}
