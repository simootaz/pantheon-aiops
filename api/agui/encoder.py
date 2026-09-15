"""Thin wrapper over ag_ui.encoder for SSE framing.

Exists so the rest of the codebase never imports the encoder directly, which
keeps the SDK upgrade surface to one file.

WHY THE ACCEPT HEADER IS PASSED THROUGH
-----------------------------------------
`EventEncoder(accept=...)` decides between SSE text and the protobuf media type.
Passing the client's header rather than hardcoding one means a client that asks
for protobuf gets it, and a browser asking for `text/event-stream` gets that -
without this module knowing which is which.

Hardcoding SSE would work today and silently ignore a client's preference, which
is the kind of thing found years later by somebody wondering why the binary
transport never engaged.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from ag_ui.core import BaseEvent
from ag_ui.encoder import EventEncoder

#: What a browser's EventSource sends and expects. Named because it is also the
#: fallback when a client sends no Accept at all - an absent header is not a
#: request for protobuf.
SSE_MEDIA_TYPE = "text/event-stream"


def encoder_for(accept: str | None) -> EventEncoder:
    """An encoder honouring the client's Accept header.

    `None` becomes SSE rather than being passed through.

    THIS IS A PIN, NOT A FIX, AND A PLANT PROVED IT
    -------------------------------------------------
    The SDK already defaults an absent accept to SSE, so removing `or
    SSE_MEDIA_TYPE` changes nothing today - a planted removal passed every test.
    That is not a hole in the guard: the test asserts the OUTCOME an absent
    header produces, which is what a caller depends on, rather than which line
    produced it.

    It stays because the default is the SDK's to change and the consequence of
    it changing is a binary stream sent to a browser that asked for nothing -
    which arrives as a blank page rather than as an error. The pin costs one
    `or`; the test that would catch the SDK changing under us is the same one
    that cannot distinguish the two today.
    """
    return EventEncoder(accept=accept or SSE_MEDIA_TYPE)


def encode(event: BaseEvent, *, accept: str | None = None) -> str:
    """One AG-UI event, framed for the wire.

    A thin pass-through, and deliberately not more: framing is the SDK's job,
    and a second implementation of it here would be one that drifts from the
    protocol the clients actually parse.
    """
    return encoder_for(accept).encode(event)


def content_type_for(accept: str | None) -> str:
    """The response Content-Type matching what `encode` will produce.

    Read off the same encoder rather than computed alongside it. Two places
    deciding the media type is two places that can disagree - and the failure is
    a stream whose frames do not match its declared type, which a client reports
    as corrupt data rather than as a header bug.
    """
    return str(encoder_for(accept).get_content_type())
