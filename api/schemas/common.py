"""HTTP-only envelopes: health, pagination and error bodies.

Domain shapes come from core.contracts and are never redefined here. Anything
in this module exists because HTTP needs it, not because the domain does.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness payload. Deliberately boring - probes should not need parsing."""

    status: Literal["ok"] = "ok"
    service: str = Field(description="Which Pantheon component answered.")
    version: str = Field(description="Running version, from the package metadata.")


# TODO: Phase 1 - add pagination and error envelopes
