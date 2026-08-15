"""Shared base for every contract model.

Contracts are closed: an unknown field is a bug, not something to ignore
silently. `extra="forbid"` enforces that at runtime and, just as importantly,
makes Pydantic emit `additionalProperties: false` into the JSON Schema - without
which the TypeScript generator bolts an `[k: string]: unknown` index signature
onto every interface and erases the closedness downstream.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base for every model exported to Go and TypeScript."""

    model_config = ConfigDict(extra="forbid")
