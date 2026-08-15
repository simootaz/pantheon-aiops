"""AG-UI event endpoint, streamed over SSE.

Supersedes api/ws/stream.py. Accepts an AG-UI run input - which carries the
client's A2UIClientCapabilities - and streams standard AG-UI events for the
lifetime of the run.

The client declares its capabilities in the run input rather than the server
guessing them, so an agent is told what the renderer accepts before it emits
anything and never produces a component that will be rejected.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - implement the SSE endpoint and the run input handshake
