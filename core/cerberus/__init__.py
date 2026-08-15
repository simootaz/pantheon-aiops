"""Cerberus - the credential broker.

Three heads: **store** (custody), **policy** (decisions), **audit** (memory).

Infrastructure beside the orchestrator, like Delphi. Not an agent: no roster
entry, no manifest.yaml, never dispatched by Zeus.

THE INVARIANT
-------------
**Agents never receive credential plaintext.** A secret in an agent's context
enters a prompt, which is sent to an LLM provider and logged there. That is an
unauditable, unrevocable exfiltration path. Assume the agent is fully
prompt-injected: it must be unable to leak what it was never given.

Credentials are brokered, never handed over:

    agent asks for a capability   (target, action, reason)
      -> Cerberus evaluates the grant
      -> no grant? Approval Gate, and a human decides
      -> Cerberus mints a lease bound to ONE connector and ONE investigation
      -> the connector redeems the lease
      -> the agent receives RESULTS ONLY

ALLOWED IMPORT SURFACE
----------------------
Code under ``agents/`` may import **only**:

    core.cerberus.broker      - to request access
    core.cerberus.redaction   - to scrub its own output

Everything else in this package produces or holds plaintext and is off limits:

    core.cerberus.redemption  - the only producer of plaintext
    core.cerberus.store.*     - holds plaintext at rest and in memory

This boundary is enforced at the import graph by
``tests/unit/test_credential_safety.py``, not by convention. A contract-surface
check alone would not catch an agent importing the store directly.

See docs/adr/0005-credential-brokering.md.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# Modules an agent may import. Anything absent from this tuple is off limits to
# code under agents/ and the boundary test will say so by name.
AGENT_IMPORTABLE: tuple[str, ...] = (
    "core.cerberus.broker",
    "core.cerberus.redaction",
)

__all__ = ["AGENT_IMPORTABLE"]

# TODO: Phase 3 - export request_access() and redact() from here
