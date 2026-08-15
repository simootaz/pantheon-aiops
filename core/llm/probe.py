"""Capability probes - models describe themselves.

Four probes per model, fired on 'Test connection' and on configuration change:

  1. trivial completion      -> reachability, auth, latency floor
  2. tool call               -> TOOL_USE
  3. JSON-schema response    -> JSON_MODE
  4. tiny image              -> VISION

Latency and cost are measured, not declared.

There is deliberately no hardcoded model table. One would be stale within weeks
and would exclude every model released after this code was written - and a
model's advertised capabilities are not always what a particular gateway
actually delivers. Probing measures the deployment, not the marketing.

Phase: 2 - Orchestrator & Investigation Flow
"""

# TODO: Phase 2 - implement the four probes and write results to the capability matrix
