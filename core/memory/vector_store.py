"""Embedding storage and similarity search backing Mnemosyne and past-incident recall.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 5 - implement embed/upsert/query against the configured vector backend.
#
# DEFERRED, with the trigger named in docs/adr/0008-memory-layer-scope.md. Its only
# consumer is Mnemosyne (Phase 5), which declares no memory tool yet, and building a
# store with no reader means guessing the query shape two phases early.
