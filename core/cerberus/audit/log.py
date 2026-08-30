"""Append-only audit log.

Append-only is the point: a trail that can be edited answers nothing. A run must
be answerable for what it touched and why, after the fact and to someone who was
not there.

APPEND-ONLY IS ENFORCED, NOT DOCUMENTED
-----------------------------------------
There is no `update`, no `delete`, and `entries()` hands back a copy. A caller
that mutates what it was given changes its own list and not the log - which is
the difference between a promise in a docstring and one a bug cannot break.

`AuditEntry` is a frozen contract model, so an entry cannot be edited after it
is appended either.

WHAT MAY BE WRITTEN HERE
--------------------------
`detail` is free text and is the one place a credential could reach the log by
accident. It is redacted on the way in - the same treatment
`core/observability/logging.py` gives a log record, and with the same literals,
because pattern rules alone do not reach a secret inside a JSON blob pasted into
a sentence. A test asserted they did; they do not, and a string has no keys for
a key-shaped rule to match.

That is the last line of defence and the first is never putting the value in the
string. A secret that was never configured is still not caught unless it is
recognisably shaped, which is stated rather than papered over.

Every other field is an identifier by construction. `credential_ref` is a
`CredentialRef`, never a value; that is what makes the whole trail safe to
attach to an Investigation an agent can read.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from core.cerberus.redaction import redact
from core.contracts.credentials import AuditEntry, AuditEvent, CredentialAction, CredentialRef


@dataclass
class AuditLog:
    """Entries, in the order they happened.

    In-process. Persisting it is the same decision as the approval gate's store
    and arrives with the same work - and a trail that must survive a restart
    needs a schema shaped by what queries it, which nothing has asked for yet.

    That is a real limitation for an audit log and it is stated rather than
    implied: today this answers "what did this run touch", not "what did this
    system touch last March".
    """

    #: Plaintext values replaced literally in `detail`. Defaulted from settings
    #: for the same reason `RedactingFilter` does: a hand-maintained list goes
    #: stale the first time a credential is added, silently.
    secrets: list[str] | None = None
    _entries: list[AuditEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.secrets is None:
            from core.observability.logging import configured_secrets

            self.secrets = configured_secrets()

    def append(
        self,
        event: AuditEvent,
        *,
        actor: str,
        investigation_id: UUID | None = None,
        credential_ref: CredentialRef | None = None,
        action: CredentialAction = CredentialAction.NOT_APPLICABLE,
        lease_id: UUID | None = None,
        detail: str = "",
    ) -> AuditEntry:
        """Record one thing that happened. The only way to change this log.

        Returns the entry so a caller can attach it somewhere without reading
        the log back and guessing which one is theirs.
        """
        entry = AuditEntry(
            id=uuid4(),
            at=datetime.now(tz=UTC),
            event=event,
            actor=actor,
            investigation_id=investigation_id,
            credential_ref=credential_ref,
            action=action,
            # Redacted on the way IN, not on the way out. A value that reached
            # storage is a value in a memory dump and in whatever persists this
            # later, whatever a reader is shown.
            detail=str(redact(detail, self.secrets)),
        )
        self._entries.append(entry)
        return entry

    def entries(
        self, *, investigation_id: UUID | None = None, event: AuditEvent | None = None
    ) -> list[AuditEntry]:
        """A COPY, filtered. Never the list itself.

        Handing back the internal list would let a caller mutate an append-only
        log by accident - `log.entries().clear()` reads as clearing a local
        variable and would empty the trail.
        """
        found = list(self._entries)
        if investigation_id is not None:
            found = [entry for entry in found if entry.investigation_id == investigation_id]
        if event is not None:
            found = [entry for entry in found if entry.event is event]
        return found

    def extend_from(self, entries: Iterable[AuditEntry]) -> None:
        """Adopt entries recorded elsewhere, preserving their order.

        For a caller that collected entries before a log existed - a run whose
        audit is assembled after the fact. Still append-only: nothing here can
        replace an entry that is already in.
        """
        self._entries.extend(entries)

    def __len__(self) -> int:
        return len(self._entries)
