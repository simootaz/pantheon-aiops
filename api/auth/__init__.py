"""Authentication and authorisation.

Identity comes from the credential, never from the payload. See
`api/auth/dependencies.py` for why that sentence is the whole module.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from api.auth.dependencies import (
    AuthMisconfigured,
    Principal,
    Role,
    authenticate,
    require,
)

__all__ = ["AuthMisconfigured", "Principal", "Role", "authenticate", "require"]
