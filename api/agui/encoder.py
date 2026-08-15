"""Thin wrapper over ag_ui.encoder for SSE framing.

Exists so the rest of the codebase never imports the encoder directly, which
keeps the SDK upgrade surface to one file.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - wrap the SDK encoder and set the SSE headers
