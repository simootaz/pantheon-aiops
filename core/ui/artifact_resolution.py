"""Resolve an ArtifactRef to a short-lived signed URL. Server-side only.

THE ONLY MODULE THAT TURNS A REFERENCE INTO A FETCHABLE URL.

This mirrors core.cerberus.redemption exactly, and for the same reason. There,
plaintext is produced in one place agents cannot import. Here, a fetchable
destination is produced in one place agents cannot import. In both cases the
agent holds a reference and the server holds the capability.

Never client-side: a signed URL minted in the browser would mean the client
could mint one for any key. Never agent-side: an agent that could resolve could
also read the result, which is the exfiltration path the ArtifactRef design
closes.

Resolution rejects a reference unless:

  1. the object exists in Pantheon's own artifact bucket - the bucket is fixed
     here, not supplied by the caller, so no arbitrary destination is
     expressible; and
  2. it belongs to the same investigation as the surface being rendered. A
     cross-investigation reference is refused, so one run cannot exfiltrate
     another run's artifacts by naming their keys.

Signed URLs are short-lived, for the same reason leases are.

See docs/adr/0006-agentic-ui-protocols.md and
docs/adr/0001-object-storage-minio.md.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from core.config import get_settings
from core.contracts.ui import ArtifactRef

#: How long a resolved URL stays fetchable.
#:
#: Short, for the reason a lease is short: the window in which a leaked URL is
#: worth anything is exactly this long. Five minutes is enough for a browser to
#: load an image and not enough to be pasted into a ticket and used tomorrow.
URL_TTL = timedelta(minutes=5)

#: What an object key may contain.
#:
#: An allowlist, and anchored. The key goes into a URL path, so a value checked
#: once it is already inside one is a value checked too late - the same lesson
#: `connectors/loki` records about label names and `connectors/github` about
#: repository paths. `..` is refused separately below.
KEY = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/\-]*\Z")


class ArtifactNotResolvable(ValueError):
    """The reference cannot be turned into a URL, and the message says why.

    One type, because every caller's next step is the same - render nothing -
    but the message distinguishes them, since "that artifact belongs to another
    investigation" and "no signer is configured" lead to very different
    conversations.
    """


class Signer(Protocol):
    """What turns a bucket and key into a fetchable URL.

    Injected rather than implemented here. Presigning is AWS SigV4, and a
    hand-rolled version of it would be an unverifiable security-critical
    function - unverifiable because there is no S3 in this repository to check
    it against, and security-critical because getting it wrong yields either a
    URL nobody can use or one that never expires.

    So the signing is somebody else's, and what lives here is the part that can
    be checked: WHICH references may be resolved at all.
    """

    def __call__(self, *, bucket: str, key: str, expires_in: int) -> str: ...


def resolve(
    ref: ArtifactRef,
    *,
    investigation_id: UUID,
    signer: Signer | None = None,
) -> str:
    """A short-lived URL for one artifact, or a refusal saying which check failed.

    `investigation_id` is what the SURFACE belongs to, supplied separately from
    the reference. Reading it off the reference would compare it against itself
    and check nothing - the same reason `core/cerberus/redemption.py` takes the
    connector and the run from its caller.
    """
    _refuse_bad_key(ref)

    if ref.investigation_id != investigation_id:
        raise ArtifactNotResolvable(
            f"artifact {ref.key} belongs to investigation {ref.investigation_id} and "
            f"is being rendered for {investigation_id}. A cross-investigation "
            "reference is how one run would exfiltrate another's artifacts by "
            "naming their keys."
        )

    if signer is None:
        raise ArtifactNotResolvable(
            "no signer is configured, so no URL can be minted. Refused rather than "
            "returning an unsigned URL: an unsigned one either fails at fetch - "
            "which reads as a broken image - or works, which would mean the bucket "
            "is public."
        )

    # The bucket is FIXED here, from configuration, and never taken from the
    # reference. That is what makes "no arbitrary destination is expressible"
    # true rather than descriptive: an ArtifactRef carries a key and nothing
    # that could name a different bucket.
    bucket = get_settings().object_storage.bucket_artifacts
    return signer(bucket=bucket, key=ref.key, expires_in=int(URL_TTL.total_seconds()))


def _refuse_bad_key(ref: ArtifactRef) -> None:
    """Refuse a key that could address something other than one object.

    Validation before substitution. A key with a `..` segment resolves out of
    the prefix it was meant to be confined to on some S3 implementations, and a
    key with a scheme in it is somebody trying to name a host.
    """
    if not ref.key or not KEY.match(ref.key):
        raise ArtifactNotResolvable(
            f"{ref.key!r} is not an artifact key. Expected letters, digits, dot, "
            "dash, underscore and slash - it is substituted into a URL, so it is "
            "validated rather than escaped after the fact."
        )
    if re.search(r"(\A|/)\.\.(/|\Z)", ref.key):
        raise ArtifactNotResolvable(
            f"{ref.key!r} contains a '..' segment. Some S3 implementations resolve "
            "it out of the prefix the key was meant to be confined to."
        )


def resolver_for(signer: Signer | None) -> Callable[[ArtifactRef, UUID], str]:
    """A resolver bound to one signer, for a caller that resolves many refs.

    Exists so a renderer holds one callable rather than passing the signer at
    every call site - and so the signer is chosen once, in the composition root,
    rather than being a parameter an agent-adjacent caller could supply.
    """

    def _resolve(ref: ArtifactRef, investigation_id: UUID) -> str:
        return resolve(ref, investigation_id=investigation_id, signer=signer)

    return _resolve
