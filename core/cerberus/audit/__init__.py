"""Head three: memory.

An append-only record of every request, grant, denial, lease mint, lease use,
revocation and rotation.

Append-only is enforced rather than documented: there is no `delete`,
`entries()` hands back a copy, and `AuditEntry` is frozen. It said "immutable"
for two phases while assignment worked fine.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.cerberus.audit.attach import (
    attach,
    record_action,
    record_approval_sought,
)
from core.cerberus.audit.log import AuditLog

__all__ = [
    "AuditLog",
    "attach",
    "record_action",
    "record_approval_sought",
]
