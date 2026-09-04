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

from dataclasses import dataclass, field, replace
from datetime import datetime

from core.cerberus.store.envelope import Sealed, rewrap, seal
from core.cerberus.store.kinds import validate
from core.contracts.credentials import CredentialRef


class CredentialNotFound(KeyError):
    """No credential is stored under that reference.

    A distinct type rather than `None`, because every caller's next step is to
    stop - and a `None` that flowed into a connector would arrive as an
    authentication failure, which reads as a wrong credential rather than a
    missing one.
    """


@dataclass(frozen=True)
class Retired:
    """A superseded value, and the moment it stops being reachable.

    Kept rather than destroyed at rotation, because a lease already issued
    against the old value must still resolve - see `store/rotation.py`. The
    window is computed from the live leases at rotation time, so there is
    nothing to configure and nothing to tune.
    """

    sealed: Sealed
    superseded_at: datetime
    retained_until: datetime

    def reachable(self, *, issued_at: datetime, now: datetime) -> bool:
        """Whether a lease issued at `issued_at` still resolves to this value.

        Both halves are needed. The first says the lease predates the rotation;
        `now < retained_until` says the window has not closed. A check on
        either alone would let an old lease reach a destroyed value, or a new
        lease reach a superseded one.

        The boundary is inclusive, and that is not a rounding choice. A lease
        issued at the exact moment of the rotation is a lease in flight - which
        is the entire population retention exists for - and a strict `<` hands
        it the new value. Under a coarse clock that is not an edge case but the
        common one: mint and rotate inside the same tick.
        """
        return issued_at <= self.superseded_at and now < self.retained_until


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
    _retired: dict[str, Retired] = field(default_factory=dict)

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
        # Shape-checked here, not at redemption. A malformed credential found at
        # 03:00 during an incident presents as the connector being broken, and
        # whoever is paged spends the first twenty minutes on the wrong system.
        validate(ref.type, value)
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

    def supersede(
        self,
        ref: CredentialRef,
        value: str,
        *,
        superseded_at: datetime,
        retained_until: datetime,
    ) -> None:
        """Store a new value, keeping the old one reachable for a window.

        The mechanism `store/rotation.py` uses. Kept here because retention is
        custody - what the vault holds and for how long - while the window
        itself is a policy question about live leases, which is rotation's.
        """
        previous = self._sealed.get(ref.id)
        self.put(ref, value)
        if previous is not None:
            self._retired[ref.id] = Retired(
                sealed=previous,
                superseded_at=superseded_at,
                retained_until=retained_until,
            )

    def version_for(self, ref: CredentialRef, *, issued_at: datetime, now: datetime) -> Sealed:
        """The version a lease issued at `issued_at` should resolve to.

        Decided by the issue time and nothing else. A version parameter would
        put the choice in the hands of whoever calls `redeem`, and the caller
        that forgot would hand a new secret to an old lease and fail
        authentication mid-rotation - which reads as a rotation that did not
        propagate.
        """
        retired = self._retired.get(ref.id)
        if retired is not None and retired.reachable(issued_at=issued_at, now=now):
            return retired.sealed
        return self.get(ref)

    def purge_retired(self, *, now: datetime) -> int:
        """Destroy retired versions past their window. Returns how many.

        Reclaims memory and changes no answer: `version_for` already refuses a
        version past its window, so a system that never purges resolves exactly
        as one that purges every second.
        """
        expired = [key for key, retired in self._retired.items() if now >= retired.retained_until]
        for key in expired:
            del self._retired[key]
        return len(expired)

    def holds(self, ref: CredentialRef) -> bool:
        return ref.id in self._sealed

    def list(self) -> list[CredentialRef]:
        """Every reference, never a value. Safe to render anywhere."""
        return sorted(self._refs.values(), key=lambda ref: ref.name)

    def delete(self, ref: CredentialRef) -> bool:
        """Forget a credential. Returns whether there was one."""
        self._refs.pop(ref.id, None)
        # The retired version goes too. A superseded value outliving the
        # credential it belongs to is reachable through a lease that predates
        # the rotation, which is a deletion that deleted nothing.
        self._retired.pop(ref.id, None)
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
        # The retired versions move too. Leaving them wrapped under the old
        # master would make a master rotation silently destroy every value a
        # live lease still resolves to - and the failure would arrive at
        # redemption as a decryption error, which reads as corruption.
        retired = {
            key: replace(
                record,
                sealed=rewrap(record.sealed, old_master=old_master, new_master=new_master),
            )
            for key, record in self._retired.items()
        }
        self._sealed = rotated
        self._retired = retired
        self.master = new_master
        return len(rotated)

    def __len__(self) -> int:
        return len(self._sealed)
