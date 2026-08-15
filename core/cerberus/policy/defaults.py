"""Safe defaults.

Production targets and ALL write actions default to ASK_EACH_TIME and cannot be
set to ALLOW_UNTIL without an explicit override flag on the grant.

The default is the security posture. Anyone can widen it deliberately; nobody
should widen it by accident.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

# TODO: Phase 3 - implement the default matrix and the override check
