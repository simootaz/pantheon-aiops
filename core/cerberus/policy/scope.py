"""Scoping: server, service, environment.

A grant for one scope must never satisfy a request in another - most
importantly, a staging grant must never satisfy a production request.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement scope matching and specificity ordering
