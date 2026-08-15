"""Cerberus entrypoint - the only module an agent may touch.

Takes an AccessRequest, evaluates policy, routes to the Approval Gate when
there is no standing grant, and mints a Lease bound to one connector and one
investigation.

It returns a Lease. It never returns plaintext, and it has no code path that
could: plaintext lives behind core.cerberus.redemption, which agents cannot
import (enforced by tests/unit/test_credential_safety.py).

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement request_access(): evaluate, approve, mint
