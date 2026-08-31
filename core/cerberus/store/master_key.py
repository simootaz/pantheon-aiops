"""Master key resolution: environment, Sealed Secret, or external KMS.

The master key is never written to disk in plaintext and never included
unencrypted in a backup - deploy/backup/ inherits this constraint from
docs/adr/0001-object-storage-minio.md.

WHAT IS IMPLEMENTED, AND WHAT IS NOT
--------------------------------------
Environment resolution only, via `CERBERUS_MASTER_KEY`. Sealed Secrets already
work through it - the secret is projected into the environment - so that path
needs no code. A KMS-backed provider does, and it is Phase 3 along with the rest
of the vault.

The chain is a function rather than a class for that reason: adding KMS means
adding a branch here, not restructuring callers.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import base64

from core.config import get_settings

#: AES-256 needs 32 bytes. Stated rather than derived from whatever was supplied,
#: because a short key silently weakens every credential wrapped with it.
KEY_BYTES = 32


class MasterKeyUnavailable(RuntimeError):
    """No master key is configured, so nothing can be encrypted or read back.

    A refusal rather than a generated fallback. A key invented at startup makes
    every credential unreadable after the next restart, and the failure surfaces
    as corrupted data rather than as missing configuration.
    """


class MasterKeyMalformed(ValueError):
    """A key is configured but is not 32 bytes of base64."""


def resolve() -> bytes:
    """The master key, or a refusal that says how to supply one."""
    configured = get_settings().cerberus.master_key
    if configured is None:
        raise MasterKeyUnavailable(
            "CERBERUS_MASTER_KEY is not set, so provider credentials cannot be "
            "encrypted or decrypted. Generate one with:\n"
            '  python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"\n'
            "and put it in the repository-root .env. Keep it: every credential "
            "already stored is unreadable without the key that wrapped it."
        )

    raw = configured.get_secret_value()
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as malformed:
        raise MasterKeyMalformed(
            "CERBERUS_MASTER_KEY is not valid base64. It should be 32 random bytes, base64-encoded."
        ) from malformed

    if len(key) != KEY_BYTES:
        raise MasterKeyMalformed(
            f"CERBERUS_MASTER_KEY decodes to {len(key)} bytes; AES-256 needs "
            f"{KEY_BYTES}. A shorter key silently weakens every credential "
            "wrapped with it, so this is refused rather than padded."
        )
    return key
