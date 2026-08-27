"""Envelope encryption: a per-credential data key, wrapped by the master key.

Rotating the master key rewraps data keys rather than re-encrypting every
credential, which is what makes rotation affordable at scale.

WHY A DATA KEY PER CREDENTIAL AND NOT ONE KEY FOR EVERYTHING
-------------------------------------------------------------
Two reasons, and only the second is about rotation.

A single key encrypting every credential means one nonce space shared by every
write. AES-GCM fails catastrophically on nonce reuse - not "degrades", but
leaks the authentication key - and a shared counter across processes is exactly
where that happens. A fresh data key per credential makes each nonce space a
single ciphertext deep.

And rotation: rewrapping N small data keys is a metadata operation, while
re-encrypting N credentials means reading and rewriting every secret in the
system. The second is the kind of job that gets deferred until it is an
incident.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.cerberus.store.master_key import KEY_BYTES, resolve

#: 96 bits, the size AES-GCM is specified for. Longer nonces are hashed down and
#: shorter ones narrow the space, so this is not a knob.
NONCE_BYTES = 12

#: Bumped when the wire format changes, so an old record is refused with an
#: explanation rather than decrypted into nonsense.
FORMAT_VERSION = 1


class DecryptionFailed(RuntimeError):
    """The ciphertext did not authenticate.

    Says nothing about *why*: a wrong master key, a truncated record and a
    tampered one are indistinguishable to AES-GCM by design, and guessing
    between them in the message would be inventing detail the cipher did not
    provide.
    """


@dataclass(frozen=True)
class Sealed:
    """One encrypted value, and everything needed to open it except the master key.

    Safe to store and safe to log in full - which is the property that makes
    envelope encryption worth the extra indirection. The wrapped data key is
    useless without the master key, and the master key never appears here.
    """

    version: int
    wrapped_key: str
    key_nonce: str
    ciphertext: str
    nonce: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "wrapped_key": self.wrapped_key,
            "key_nonce": self.key_nonce,
            "ciphertext": self.ciphertext,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Sealed:
        version = int(raw.get("version", 0))
        if version != FORMAT_VERSION:
            raise DecryptionFailed(
                f"sealed record is format version {version}; this build writes and "
                f"reads version {FORMAT_VERSION}. Refusing rather than guessing at "
                "an older layout."
            )
        return cls(
            version=version,
            wrapped_key=str(raw["wrapped_key"]),
            key_nonce=str(raw["key_nonce"]),
            ciphertext=str(raw["ciphertext"]),
            nonce=str(raw["nonce"]),
        )


def seal(plaintext: str, *, master: bytes | None = None) -> Sealed:
    """Encrypt one value under a fresh data key, wrapped by the master key."""
    master_key = master if master is not None else resolve()
    data_key = os.urandom(KEY_BYTES)
    key_nonce = os.urandom(NONCE_BYTES)
    nonce = os.urandom(NONCE_BYTES)

    return Sealed(
        version=FORMAT_VERSION,
        wrapped_key=_b64(AESGCM(master_key).encrypt(key_nonce, data_key, None)),
        key_nonce=_b64(key_nonce),
        ciphertext=_b64(AESGCM(data_key).encrypt(nonce, plaintext.encode("utf-8"), None)),
        nonce=_b64(nonce),
    )


def open_sealed(sealed: Sealed, *, master: bytes | None = None) -> str:
    """Decrypt, or raise. Never returns a partial or a placeholder."""
    master_key = master if master is not None else resolve()
    try:
        data_key = AESGCM(master_key).decrypt(
            _unb64(sealed.key_nonce), _unb64(sealed.wrapped_key), None
        )
        plaintext = AESGCM(data_key).decrypt(_unb64(sealed.nonce), _unb64(sealed.ciphertext), None)
    except (InvalidTag, ValueError) as failure:
        raise DecryptionFailed(
            "the sealed value did not authenticate. The master key may be the "
            "wrong one, or the record may have been altered - AES-GCM cannot "
            "distinguish those and neither can this message."
        ) from failure
    return plaintext.decode("utf-8")


def rewrap(sealed: Sealed, *, old_master: bytes, new_master: bytes) -> Sealed:
    """Move a record to a new master key without touching its ciphertext.

    The whole point of the envelope: the credential itself is never decrypted
    and re-encrypted, so rotation costs one small operation per record rather
    than a full read-modify-write of every secret in the system.
    """
    data_key = AESGCM(old_master).decrypt(
        _unb64(sealed.key_nonce), _unb64(sealed.wrapped_key), None
    )
    key_nonce = os.urandom(NONCE_BYTES)
    return Sealed(
        version=sealed.version,
        wrapped_key=_b64(AESGCM(new_master).encrypt(key_nonce, data_key, None)),
        key_nonce=_b64(key_nonce),
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
    )


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value)
