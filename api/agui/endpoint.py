"""AG-UI event endpoint, streamed over SSE.

Supersedes api/ws/stream.py. Accepts an AG-UI run input - which carries the
client's A2UIClientCapabilities - and streams standard AG-UI events for the
lifetime of the run.

The client declares its capabilities in the run input rather than the server
guessing them, so an agent is told what the renderer accepts before it emits
anything and never produces a component that will be rejected.

WHAT THIS STREAMS, AND WHAT IT REFUSES TO
-------------------------------------------
Events for **one** investigation, named by `thread_id`. Not everything on the
bus: a stream of every run in the system would hand one viewer another tenant's
incidents, and `api/routers/investigations.py` already establishes that reading
somebody else's run answers 404.

CAPABILITIES ARE CHECKED, NOT TRUSTED AND NOT IGNORED
-------------------------------------------------------
A client that declares a component catalog missing something Pantheon emits is
told at handshake time, in the response, rather than being sent a surface it
will drop in silence. A dropped approval prompt is an approval nobody is asked
for, and the run waits forever on a person who was never shown anything.

Pantheon emits a fixed, small set of component types - `a2ui_channel` builds
every surface - so the check is a subset test against something knowable rather
than a guess about what an agent might produce.

THE STREAM ENDS WHEN THE RUN DOES
-----------------------------------
`RunFinished` or `RunError` closes it. A stream left open after a run finished
is a client holding a connection for events that will never come, and on a
server it is a file descriptor per abandoned tab.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from ag_ui.core import BaseEvent, EventType, RunErrorEvent
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.agui import a2ui_channel
from api.agui.encoder import content_type_for, encode
from api.agui.translator import translate
from api.auth.dependencies import Principal, Role, require
from api.routers.investigations import get_store
from core.contracts.investigation import Investigation
from core.contracts.ui import A2UIComponentType, UIActionResponse
from core.store.investigations import InvestigationStore

router = APIRouter(prefix="/agui", tags=["agui"])

#: Component types every Pantheon surface is built from. A client whose catalog
#: is missing one of these cannot render an approval prompt.
#:
#: Derived from what `a2ui_channel` actually emits rather than from the whole
#: `A2UIComponentType` enum: the enum is the allowlist of what MAY be emitted,
#: and demanding a client support all of it would reject renderers over
#: components nothing ever sends.
REQUIRED_COMPONENTS: frozenset[A2UIComponentType] = frozenset(
    {
        A2UIComponentType.CARD,
        A2UIComponentType.ROW,
        A2UIComponentType.TEXT,
        A2UIComponentType.BUTTON,
    }
)

#: How long to wait for the next event before sending a keep-alive comment.
#:
#: Proxies and load balancers close an idle connection, commonly at 60s. An
#: investigation can be quiet for longer than that while an agent reads a slow
#: window, and a stream dropped mid-run looks to a client like the run ended.
KEEPALIVE_SECONDS = 20.0


async def _events_for(
    request: Request, investigation_id: UUID, store: InvestigationStore
) -> AsyncIterator[BaseEvent]:
    """Every AG-UI event for one investigation.

    Reads the Investigation once for the opening snapshot, then follows the bus.
    Re-reading the store per event would make the edge slower than the run it is
    describing.
    """
    investigation = await store.get(investigation_id)
    if investigation is not None:
        for event in translate(_synthetic_start(investigation), investigation=investigation):
            yield event

    queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
    subscribe = getattr(request.app.state, "agui_subscribe", None)
    if subscribe is None:
        # Nothing to follow. The snapshot still went out, so a client sees the
        # run as it stands rather than an empty screen - and the stream closes
        # instead of hanging on a subscription that does not exist.
        return

    unsubscribe = subscribe(investigation_id, queue)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
            except TimeoutError:
                continue
            yield event
            if event.type in (EventType.RUN_FINISHED, EventType.RUN_ERROR):
                return
    finally:
        unsubscribe()


def _synthetic_start(investigation: Investigation) -> Any:
    """A `trigger_received` for the run as it already stands.

    The stream has to open with a snapshot, and the translator builds one from
    that event. Constructing it here rather than adding a "send a snapshot"
    branch keeps one path from event to wire - a second path is a second place
    the snapshot shape can drift from the patches that follow it.
    """
    from core.contracts.events import TriggerReceivedEvent

    return TriggerReceivedEvent(investigation_id=investigation.id, trigger=investigation.trigger)


@router.get("/{investigation_id}", summary="Stream one investigation as AG-UI events")
async def stream(
    investigation_id: UUID,
    request: Request,
    store: Annotated[InvestigationStore, Depends(get_store)],
    principal: Annotated[Principal, require(Role.VIEWER, Role.OPERATOR, Role.APPROVER, Role.ADMIN)],
    accept: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Stream this investigation. 404 for one belonging to another tenant.

    404 rather than 403, the same as `GET /investigations/{id}`: a 403 confirms
    the run exists, and for tenant isolation existence is itself the disclosure.
    """
    investigation = await store.get(investigation_id)
    if investigation is None or not principal.reads(investigation.tenant):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation {investigation_id}",
        )

    async def frames() -> AsyncIterator[str]:
        async for event in _events_for(request, investigation_id, store):
            yield encode(event, accept=accept)

    return StreamingResponse(
        frames(),
        media_type=content_type_for(accept),
        headers={
            # Proxies buffer by default and a buffered event stream arrives in
            # one lump when the run ends, which is the opposite of the point.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{investigation_id}/actions", summary="Answer an A2UI surface")
async def act(
    investigation_id: UUID,
    message: dict[str, Any],
    store: Annotated[InvestigationStore, Depends(get_store)],
    principal: Annotated[Principal, require(Role.APPROVER, Role.OPERATOR, Role.ADMIN)],
) -> UIActionResponse:
    """Accept one returning client action message.

    VIEWER is deliberately absent from the roles: every action this accepts is a
    decision, and a read-only principal answering an approval prompt would make
    the role name a description rather than a permission.

    The response is the parsed `UIActionResponse` and nothing is executed here.
    Routing an approval to the gate and an access decision to the broker is
    those modules' work, and they re-validate - `may_execute` checks the
    approval against the Action *as it is now*, which a route that acted on the
    surface id alone would bypass.
    """
    investigation = await store.get(investigation_id)
    if investigation is None or not principal.reads(investigation.tenant):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no investigation {investigation_id}",
        )

    try:
        return a2ui_channel.from_wire(message)
    except a2ui_channel.UnknownClientAction as refused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(refused)
        ) from refused


def unsupported_components(declared: list[A2UIComponentType]) -> list[str]:
    """Components Pantheon emits that this client says it cannot render.

    Returned rather than raised, so a caller decides whether an unrenderable
    approval prompt is a refusal or a warning. What it must not be is silence:
    a dropped approval prompt is an approval nobody is asked for, and the run
    waits forever on a person who was never shown anything.
    """
    return sorted(one.value for one in REQUIRED_COMPONENTS - set(declared))


def error_event(message: str, *, code: str = "pantheon.error") -> RunErrorEvent:
    """The one way a run failure reaches a client.

    A stream that simply stopped would be indistinguishable from a network drop,
    and a client cannot tell whether to retry.
    """
    return RunErrorEvent(type=EventType.RUN_ERROR, message=message, code=code)
