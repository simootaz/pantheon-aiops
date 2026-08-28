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


class AgentSummary(BaseModel):
    """One row of the roster.

    `implemented` is the field that matters and the reason this envelope exists
    rather than returning `AgentManifest` directly. Ten manifests validate; one
    agent runs. A listing without this would say Pantheon has ten working
    agents, which is the most misleading thing this API could report.

    It is read from the dispatcher's registry, not from the manifest - a
    manifest describes an intention and cannot know whether anyone implemented
    it.
    """

    codename: str
    domain: str
    description: str
    capabilities: list[str] = Field(
        default_factory=list, description="Capability names, not their full definitions."
    )
    tools: list[str] = Field(
        default_factory=list, description="The manifest's tool allowlist, verbatim."
    )
    implemented: bool = Field(
        description="Whether an implementation is registered. False means a stub."
    )


class BuildInfo(BaseModel):
    """What is actually running, for the question asked after an incident."""

    service: str
    version: str
    python: str = Field(description="Interpreter version, since behaviour depends on it.")


class ReadinessCheck(BaseModel):
    """One dependency, and whether it answered."""

    name: str
    ready: bool
    detail: str = Field(default="", description="Why not, when it did not.")


class ReadinessResponse(BaseModel):
    """Readiness, and the checks behind it.

    The checks are returned rather than collapsed into the boolean. A probe
    reads `ready`; a human reads why - and "not ready" with nothing to look at
    is the state that costs an hour at three in the morning.
    """

    ready: bool
    service: str
    checks: list[ReadinessCheck] = Field(default_factory=list)


# TODO: Phase 4 - add pagination and error envelopes.
#
# `GET /investigations` takes a `limit` and returns newest-first, which is the
# whole of what a `recent()` store offers. Pagination needs a caller that scrolls,
# and that is the dashboard's investigation list.
