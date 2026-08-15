"""Cerberus AccessRequest as an A2UI surface.

Renders the agent's stated reason, the exact scope, the lease TTL and the
investigation id - because approving "an agent wants database access" is not a
decision, and approving a stated hypothesis is.

The returning action reaches Cerberus, which re-validates it against the request
it claims to answer. A surface cannot grant anything by itself.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - build the access-request surface and map its action back to Cerberus
