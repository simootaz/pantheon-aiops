"""Dialect adapters.

Named by wire format, never by vendor: a dialect outlives the vendor that
popularised it, several vendors speak each one, and a vendor-named module
implies a coupling that does not exist.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 5 - expose the adapter lookup by Dialect.
#
# One adapter exists, so a lookup would be a dict with one entry and a caller
# that could not be wrong. `core/llm/assembly.py` refuses any other dialect by
# name, which is the same check with a better error. The lookup earns its keep
# when there is more than one thing to look up.
