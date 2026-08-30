"""Encrypted credential storage.

Credentials are stored envelope-encrypted and are only ever decrypted in
response to a valid lease redemption.

THE VAULT HAS NO PLAINTEXT GETTER
-----------------------------------
`get()` returns a `Sealed` record. There is deliberately no `get_plaintext`,
and adding one would make this module a second producer of secrets - which is
the exact thing `core/cerberus/redemption.py` exists to be the only one of.

That matters more than it looks. `tests/unit/test_credential_safety.py` forbids
agents from importing `core.cerberus.store` at all, and the reason that boundary
is enforceable is that everything behind it deals in sealed bytes. A convenience
method here would put a decrypt one import away from an agent.

Opening a sealed record needs the master key, which lives in
`core/cerberus/store/master_key.py` and is resolved at the moment of redemption
rather than held here - so a vault dumped from memory yields ciphertext.

WHAT IS STORED, AND WHAT IS NOT
---------------------------------
A `CredentialRef` and a sealed value. The ref is safe to hand anywhere: it
identifies without disclosing, and it is what an Investigation and a lease
carry. The value never leaves in the shape it went in.

Rotation rewraps rather than re-encrypts - see `envelope.rewrap` - so moving to
a new master key is one small operation per record rather than reading and
rewriting every secret in the system.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.cerberus.store.envelope import Sealed, rewrap, seal
from core.contracts.credentials import CredentialRef


class CredentialNotFound(KeyError):
    """No credential is stored under that reference.

    A distinct type rather than `None`, because every caller's next step is to
    stop - and a `None` that flowed into a connector would arrive as an
    authentication failure, which reads as a wrong credential rather than a
    missing one.
    """


@dataclass
class Vault:
    """Sealed credentials, keyed by reference id.

    In-process, like the rest of Phase 3's stores. The envelope is what makes
    that tolerable: the values are ciphertext wherever they sit, so persisting
    this later is a change of container rather than a change of exposure.
    """

    master: bytes | None = None
    _sealed: dict[str, Sealed] = field(default_factory=dict)
    _refs: dict[str, CredentialRef] = field(default_factory=dict)

    def put(self, ref: CredentialRef, value: str) -> None:
        """Store a credential, sealed. Replaces any existing one for that ref.

        The plaintext is not kept: it is sealed here and the parameter goes out
        of scope. Nothing in this class holds a decrypted value at any point.
        """
        if not value:
            raise ValueError(
                f"refusing to store an empty credential for {ref.name}. An empty "
                "value authenticates as nothing and fails as though the credential "
                "were wrong, which sends whoever debugs it to the provider."
            )
        self._sealed[ref.id] = seal(value, master=self.master)
        self._refs[ref.id] = ref

    def get(self, ref: CredentialRef) -> Sealed:
        """The SEALED record. Opening it is redemption's job, not this module's."""
        try:
            return self._sealed[ref.id]
        except KeyError as missing:
            raise CredentialNotFound(
                f"no credential stored for {ref.name} ({ref.id}). Stored: {sorted(self._refs)}"
            ) from missing

    def holds(self, ref: CredentialRef) -> bool:
        return ref.id in self._sealed

    def list(self) -> list[CredentialRef]:
        """Every reference, never a value. Safe to render anywhere."""
        return sorted(self._refs.values(), key=lambda ref: ref.name)

    def delete(self, ref: CredentialRef) -> bool:
        """Forget a credential. Returns whether there was one."""
        self._refs.pop(ref.id, None)
        return self._sealed.pop(ref.id, None) is not None

    def rotate_master(self, *, old_master: bytes, new_master: bytes) -> int:
        """Move every record to a new master key. Returns how many moved.

        Rewraps the per-credential data keys and leaves the ciphertext
        untouched, which is the whole reason the envelope exists: rotation is a
        metadata operation rather than a full read-and-rewrite of every secret.

        All or nothing. A partial rotation leaves some records readable only
        with the old key and some only with the new, and nothing on a record
        says which - so a failure part-way through would be discovered as
        corruption.
        """
        rotated = {
            key: rewrap(sealed, old_master=old_master, new_master=new_master)
            for key, sealed in self._sealed.items()
        }
        self._sealed = rotated
        self.master = new_master
        return len(rotated)

    def __len__(self) -> int:
        return len(self._sealed)
