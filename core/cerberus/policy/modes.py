"""Permission modes: Deny, Ask each time, Allow for this investigation, Allow until.

ALLOW_FOR_INVESTIGATION expires with the run that requested it, so a broad
approval cannot outlive the reason it was given.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement mode evaluation and expiry semantics
