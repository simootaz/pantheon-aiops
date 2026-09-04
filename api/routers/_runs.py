"""Handing an accepted trigger to Zeus, for whichever receiver accepted it.

WHY THIS IS ONE MODULE AND NOT THREE COPIES
---------------------------------------------
Three endpoints accept something that should start an investigation: an
Alertmanager notification, a GitLab hook and a GitHub hook. All three need the
same four things - a background task, an injectable runner so a unit test does
not open sockets, a swallowed exception because nothing is listening after the
response, and the investigation id returned before the run finishes.

This lived in `alerts.py` as private functions while it had one caller. Copying
it to the other two would be three implementations of "run Zeus safely", and the
one that drifts is the one whose endpoint nobody exercises.

WHY THE FAILURE IS SWALLOWED
------------------------------
The task runs after the response has been sent, so an exception here reaches
nobody: no client, no status code, no retry. It is logged, and Zeus itself
records a FAILED Investigation for anything it can attribute - which is the path
a reader will actually see.

Re-raising would put a traceback in the server log and change nothing else,
while looking from the code like the error was handled.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from fastapi import Request

from core.bus import EventBus
from core.contracts.investigation import Trigger
from core.orchestrator.router import investigate
from core.store.investigations import InvestigationStore

logger = logging.getLogger(__name__)


class InvestigationRunner(Protocol):
    """What a receiver hands an accepted trigger to."""

    async def __call__(
        self,
        *,
        trigger: Trigger,
        investigation_id: UUID,
        store: InvestigationStore,
        bus: EventBus,
    ) -> None: ...


def runner_for(request: Request) -> InvestigationRunner:
    """What actually runs an accepted trigger, from application state.

    Injectable because the default reaches Prometheus and Postgres, and a unit
    test that exercises a receiver would otherwise open sockets as a side effect
    of asserting a 202. Substituting a recorder keeps those tests offline and
    makes "this endpoint schedules an investigation" an assertion rather than a
    consequence nobody checks.
    """
    runner: InvestigationRunner | None = getattr(request.app.state, "investigation_runner", None)
    return runner if runner is not None else run_investigation


async def run_investigation(
    *,
    trigger: Trigger,
    investigation_id: UUID,
    store: InvestigationStore,
    bus: EventBus,
) -> None:
    """Run Zeus for an accepted trigger, and never raise.

    See the module docstring: this runs after the response, so an exception
    reaches nobody.
    """
    try:
        await investigate(
            trigger,
            store=store,
            bus=bus,
            investigation_id=investigation_id,
        )
    except Exception:
        logger.exception("investigation %s failed", investigation_id)
