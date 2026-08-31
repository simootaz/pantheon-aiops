"""Head one: custody.

Encrypted storage for every credential type. Holds plaintext at rest and in
memory, so it sits behind the same import boundary as redemption.py - agents
must not import anything under this package.

WHAT IS EXPORTED, AND WHAT IS NOT
-----------------------------------
`Vault`, `Sealed` and the rotation entry points. Not `open_sealed`: it is the
one function that turns ciphertext back into a credential, and re-exporting it
here would put a decrypt one import shallower than it is - which is the entire
distance this package's boundary is made of.

`core/cerberus/redemption.py` imports it directly and is the only module that
should.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from core.cerberus.store.envelope import Sealed
from core.cerberus.store.kinds import CredentialMalformed, Handoff, kind_of, validate
from core.cerberus.store.rotation import Rotation, purge, rotate
from core.cerberus.store.vault import CredentialNotFound, Retired, Vault

__all__ = [
    "CredentialMalformed",
    "CredentialNotFound",
    "Handoff",
    "Retired",
    "Rotation",
    "Sealed",
    "Vault",
    "kind_of",
    "purge",
    "rotate",
    "validate",
]
