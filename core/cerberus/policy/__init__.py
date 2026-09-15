"""Head two: decisions.

Evaluates whether an agent may reach a credential, in what way, and for how
long.

The entrypoint is `evaluate`. Everything else here is the machinery it uses:
`scope` decides which grants are about a request, `modes` decides what one
grant says, `grants` picks which of several answers, `defaults` says what
happens when none of them do, and `revocation` takes permission back.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import datetime

from core.cerberus.policy.grants import GrantBook
from core.cerberus.policy.modes import Answer, Verdict
from core.contracts.credentials import AccessRequest

__all__ = ["Answer", "GrantBook", "Verdict", "evaluate"]


def evaluate(request: AccessRequest, *, grants: GrantBook, now: datetime) -> Verdict:
    """Whether this access is allowed, must be asked about, or is refused.

    A thin name over `GrantBook.evaluate`, kept because the entrypoint is the
    part callers should depend on: the broker asks the policy a question, and
    which book answers it is not the broker's business.
    """
    return grants.evaluate(request, now=now)
