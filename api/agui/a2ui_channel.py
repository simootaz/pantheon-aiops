"""The single seam where A2UI payloads enter the AG-UI event stream.

⚠️ UNRESOLVED AGAINST THE SPECIFICATIONS ⚠️

AG-UI advertises day-zero A2UI compatibility, and A2UI names AG-UI as a
transport - but A2UI v0.9.1 defines its message mapping against **A2A message
Parts**, and no canonical AG-UI envelope for an A2UI payload is documented in
either specification. Published examples improvise: one uses a `GenerativeUI`
event with `format: "a2ui"` alongside a `MessageDelta` event, and `MessageDelta`
is not an AG-UI event type at all.

Rather than invent an envelope and scatter the guess across the codebase, the
guess lives here, once. Pantheon emits A2UI as an AG-UI `Custom` event named
`a2ui`, carrying one A2UI message per event.

IF A CANONICAL ENVELOPE IS STANDARDISED
---------------------------------------
Exactly two things change, both in this file:

1. ``EVENT_NAME`` / the choice of `Custom` - the AG-UI event actually used.
2. ``to_wire()`` - the payload shape wrapped inside it.

Nothing else in Pantheon constructs an A2UI wire message. `core/ui/` builds
A2UISurface objects; `translator.py` decides *when* to emit; only this module
decides *how*. The cost of being wrong is bounded to one function and one
constant, and that is the entire reason this seam exists.

See docs/adr/0006-agentic-ui-protocols.md and the ROADMAP row tracking it.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

#: Name carried on the AG-UI `Custom` event. Change here if a canonical
#: envelope is standardised - and nowhere else.
EVENT_NAME = "a2ui"

#: A2UI server-to-client message types Pantheon emits. `deleteSurface` is
#: included for completeness; `updateDataModel` is emitted when a surface's
#: bound values change without its structure changing.
MESSAGE_TYPES = (
    "createSurface",
    "updateComponents",
    "updateDataModel",
    "deleteSurface",
)

# TODO: Phase 4 - implement to_wire(surface) -> the Custom event payload, and
# from_wire() for the returning client action message
