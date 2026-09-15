"""Per-type handling: database, SSH, kubeconfig, HTTP auth, cloud key, TLS, key-value.

Each type knows how to validate its own shape and how to hand itself to a
connector at redemption time. None of them is a contract model.

HOW A CREDENTIAL REACHES A CONNECTOR IS A SECURITY PROPERTY
-------------------------------------------------------------
Not a formatting detail. A kubeconfig passed as a command-line argument sits in
`ps` output for every process on the box and in the shell history of whoever
ran it; the same bytes in a 0600 file do not. A token in a URL query string is
in the reverse proxy's access log; in an `Authorization` header it is not.

So the handoff is declared per type and `ARGUMENT` is refused outright. There is
no credential type for which the command line is the right channel, and a
refusal here costs an adapter while the alternative costs a log full of
secrets nobody knows are there.

VALIDATION CATCHES SHAPE, NEVER CORRECTNESS
---------------------------------------------
A syntactically perfect connection string pointing at a decommissioned host
validates. Nothing here contacts anything.

It runs at PUT time rather than at redemption for the same reason
`policy.defaults` refuses an unsafe grant at registration: a malformed
credential discovered at 03:00 during an incident presents as the connector
being broken, and whoever is paged spends the first twenty minutes on the wrong
system.

ONE CHECK IS NOT COSMETIC
---------------------------
A CR or LF inside an HTTP credential splits the request that carries it. That
is header injection, it is reachable by anybody who can set a credential, and
it is checkable here in one line - so it is checked here rather than trusted to
whichever client library happens to be in use.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from dataclasses import dataclass

from core.contracts.credentials import ConnectionDescriptor, CredentialType, Handoff

#: The one handoff that is never correct. Named rather than simply omitted, so
#: that a type declaring it fails loudly instead of falling through a lookup.
FORBIDDEN_HANDOFF = Handoff.ARGUMENT


class CredentialMalformed(ValueError):
    """The credential cannot be what its type says it is."""


@dataclass(frozen=True)
class Kind:
    """What one credential type is, and how it travels."""

    type: CredentialType
    handoff: Handoff
    #: What the connector calls it. A file path for FILE, a variable name for
    #: ENVIRONMENT, a header name for HEADER.
    channel: str

    def descriptor(self) -> ConnectionDescriptor:
        """The wire form, for anything that may not import this package.

        Built here rather than declared twice. Two definitions of "how a
        kubeconfig travels" is one that can disagree with the other, and the
        one a dashboard reads would be the one nobody tests.
        """
        return ConnectionDescriptor(type=self.type, handoff=self.handoff, channel=self.channel)

    def validate(self, value: str) -> None:
        """Refuse a value that cannot be what this type claims.

        Shape only. `_CHECKS` holds the per-type rule; a type with no rule is
        checked for emptiness alone, which is not a gap - a cloud key is an
        opaque string and inventing a pattern for it would reject the next
        provider's format for no reason.
        """
        if not value.strip():
            raise CredentialMalformed(
                f"a {self.type.value} credential is empty. It authenticates as "
                "nothing and fails as though the credential were wrong."
            )
        if self.handoff is Handoff.HEADER and ("\n" in value or "\r" in value):
            raise CredentialMalformed(
                f"a {self.type.value} credential travels in the {self.channel} header "
                "and contains a newline. That splits the request carrying it - it is "
                "header injection, reachable by anyone who can set a credential."
            )
        check = _CHECKS.get(self.type)
        if check is not None:
            check(self, value)


def _database(kind: Kind, value: str) -> None:
    """A URI with a scheme and something after it.

    Deliberately not a full URI parse. `postgres://user:pw@host/db` and
    `host=db user=x` are both valid ways to say the same thing, and rejecting
    the second would refuse a correct credential to enforce a preference.
    """
    if "://" not in value and "=" not in value:
        raise CredentialMalformed(
            f"a {kind.type.value} credential is neither a URI (scheme://...) nor a "
            f"keyword string (host=... user=...): {value[:12]}..."
        )


def _pem(kind: Kind, value: str) -> None:
    """A PEM block, opened and closed.

    The closing line matters. A truncated key - copied from a terminal that
    wrapped, or a file read short - has a BEGIN and no END, and it fails at use
    with a parse error from deep inside a crypto library.
    """
    if "-----BEGIN" not in value or "-----END" not in value:
        raise CredentialMalformed(
            f"a {kind.type.value} credential is not a complete PEM block. A BEGIN "
            "with no END is how a key copied from a wrapped terminal arrives, and "
            "it fails at use with a parse error from inside a crypto library."
        )


def _kubeconfig(kind: Kind, value: str) -> None:
    """The three sections a kubeconfig is useless without."""
    missing = [section for section in ("clusters", "contexts", "users") if section not in value]
    if missing:
        raise CredentialMalformed(
            f"a kubeconfig without {', '.join(missing)} cannot select a cluster to "
            "talk to. Stored as-is it would fail at use as an authentication error."
        )


_CHECKS = {
    CredentialType.DATABASE: _database,
    CredentialType.SSH: _pem,
    CredentialType.TLS: _pem,
    CredentialType.KUBECONFIG: _kubeconfig,
}


#: Every type, with the channel it travels through.
#:
#: A file for anything multi-line: a PEM key or a kubeconfig in an environment
#: variable survives, but it is in `/proc/<pid>/environ` for the life of the
#: process and in every crash dump and child process it spawns.
KINDS = {
    CredentialType.DATABASE: Kind(CredentialType.DATABASE, Handoff.ENVIRONMENT, "DATABASE_URL"),
    CredentialType.SSH: Kind(CredentialType.SSH, Handoff.FILE, "id_ed25519"),
    CredentialType.KUBECONFIG: Kind(CredentialType.KUBECONFIG, Handoff.FILE, "kubeconfig"),
    CredentialType.HTTP_AUTH: Kind(CredentialType.HTTP_AUTH, Handoff.HEADER, "Authorization"),
    CredentialType.CLOUD_KEY: Kind(
        CredentialType.CLOUD_KEY, Handoff.ENVIRONMENT, "CLOUD_CREDENTIALS"
    ),
    CredentialType.TLS: Kind(CredentialType.TLS, Handoff.FILE, "tls.pem"),
    CredentialType.KEY_VALUE: Kind(CredentialType.KEY_VALUE, Handoff.ENVIRONMENT, "SECRET"),
}


def kind_of(credential_type: CredentialType) -> Kind:
    """The handling for one type.

    Raises rather than defaulting. A type with no entry is one somebody added
    to the enum without deciding how it travels, and defaulting it to an
    environment variable would make that omission invisible - a kubeconfig-sized
    secret would land in `/proc/<pid>/environ` because nobody finished a commit.
    """
    try:
        kind = KINDS[credential_type]
    except KeyError as unknown:
        raise CredentialMalformed(
            f"no handling declared for {credential_type.value}. Every credential "
            "type must say how it reaches a connector; defaulting would hide the "
            "omission behind a channel nobody chose."
        ) from unknown

    if kind.handoff is FORBIDDEN_HANDOFF:  # pragma: no cover - guarded by test
        raise CredentialMalformed(
            f"{credential_type.value} declares the {FORBIDDEN_HANDOFF.value} handoff. "
            "A credential on the command line is in `ps` output for every process "
            "on the box and in somebody's shell history."
        )
    return kind


def validate(credential_type: CredentialType, value: str) -> None:
    """Refuse a value that cannot be what its type claims. Shape only."""
    kind_of(credential_type).validate(value)
