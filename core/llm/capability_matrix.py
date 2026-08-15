"""What each model can actually do, as measured.

Stores probe results per (provider, model): capabilities, context window, cost
and latency, with the timestamp of the last probe.

This is a cache of observations, not a table of facts - entries go stale when a
provider changes what sits behind a stable model id, so `last_probed_at` is part
of the record and is surfaced in the settings UI.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement storage, staleness policy and query-by-requirements
