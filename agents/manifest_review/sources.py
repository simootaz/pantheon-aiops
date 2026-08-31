"""Turning a pull request's files into the before/after pairs Aegis reviews.

WHY THIS IS NOT A DIFF PARSER
-------------------------------
A pull request's `files` entries carry a unified `patch`, and reconstructing
before/after from one is possible. It is wrong here twice over.

GitHub **omits `patch` entirely** for a file above roughly 20k of diff and for
anything it considers binary, so a reviewer built on patches would silently skip
the large manifest changes most worth reviewing and report a clean run. And
applying a unified diff correctly is an algorithm whose failure mode is a
plausible document - a mis-applied hunk produces YAML that parses.

So the bytes are fetched at both shas and parsed. `connectors/github.file_at`
does the fetching; everything here is pure.

DOCUMENTS ARE PAIRED BY IDENTITY, NOT BY POSITION
---------------------------------------------------
A manifest file holds several YAML documents separated by `---`, and they get
reordered. Pairing the first document in the old file with the first in the new
would report a Deployment being replaced by a Service every time somebody sorts
a file - a diff full of enormous findings, none of them real.

So each document is keyed by what identifies a Kubernetes object: kind, name and
namespace. Reordering then changes nothing, which is correct, and a genuine
rename shows up as one removal and one addition, which is what it is.

A DOCUMENT WITHOUT `apiVersion` AND `kind` IS NOT A MANIFEST
--------------------------------------------------------------
Extension is not enough. `.gitlab-ci.yml`, a Helm `values.yaml` and a
`docker-compose.yml` are all YAML and none is a Kubernetes object, and reviewing
one as though it were produces findings about fields it was never going to have.

`apiVersion` plus `kind` is what makes a document a Kubernetes object - that is
the API's own rule, not a heuristic about names.

WHAT FAILS LOUDLY
-------------------
A file that does not parse is reported, not skipped. A skipped file is a file
reviewed as unchanged, and the run comes back clean having looked at nothing.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any

import yaml

#: Extensions worth opening at all. A first filter, not the test - a document
#: still has to carry `apiVersion` and `kind` to be reviewed.
MANIFEST_SUFFIXES = (".yaml", ".yml")


class UnreadableManifest(ValueError):
    """A file that was supposed to be a manifest and could not be read as one."""


@dataclass(frozen=True)
class Identity:
    """What identifies one Kubernetes object across two revisions.

    Namespace included, because `default/checkout` and `staging/checkout` are
    two objects and pairing them would report every promotion as a change to
    one workload.

    `apiVersion` is deliberately NOT part of it. A migration from
    `apps/v1beta1` to `apps/v1` is the same Deployment moving, and keying on the
    version would report it as one object deleted and another created - which is
    the loudest possible finding for the most routine possible change.
    """

    kind: str
    name: str
    namespace: str | None

    def __str__(self) -> str:
        where = f"{self.namespace}/" if self.namespace else ""
        return f"{where}{self.kind}/{self.name}"


@dataclass
class Change:
    """One object's two revisions. Either side may be absent."""

    identity: Identity
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def as_pair(self) -> dict[str, Any]:
        """The shape `Aegis.investigate` reads off `ctx.params`."""
        return {"before": self.before, "after": self.after}


@dataclass
class Extraction:
    """Every change found, and every file that could not be read.

    Both, deliberately. A caller that got only the changes would review a pull
    request in which half the files failed to parse and report it clean.
    """

    changes: list[Change] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unreadable


def looks_like_manifest_file(path: str) -> bool:
    """Whether this path is worth opening.

    A cheap first pass over the file list so a pull request touching a hundred
    Go files costs no requests. The real test is per document, below.
    """
    return path.lower().endswith(MANIFEST_SUFFIXES)


def decode(payload: dict[str, Any]) -> str:
    """The text of a `file_at` response.

    GitHub base64-encodes it, with newlines inside the encoded string that
    `b64decode` tolerates. An encoding this does not recognise is refused rather
    than returned empty, because empty text yields no documents and reviews as
    "everything was removed".
    """
    encoding = payload.get("encoding")
    if encoding != "base64":
        raise UnreadableManifest(
            f"github encoded this file as {encoding!r}, which this reader does not "
            "understand. Returning empty text would review as 'everything was removed'."
        )
    try:
        return base64.b64decode(payload.get("content", "")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as broken:
        raise UnreadableManifest(f"could not decode the file: {broken}") from broken


def documents(text: str, *, path: str = "<memory>") -> list[dict[str, Any]]:
    """Every Kubernetes object in one file.

    `safe_load_all`, never `load_all`. Full YAML loading constructs arbitrary
    Python objects from a document, and these documents come from a pull request
    - which is to say, from whoever opened it.

    Non-object documents are dropped rather than refused: a file legitimately
    holds a `---` separator with nothing after it, and Helm templates leave empty
    documents behind. A file that holds no objects at all simply contributes
    none, which is different from failing to parse.
    """
    try:
        loaded = list(yaml.safe_load_all(text))
    except yaml.YAMLError as broken:
        raise UnreadableManifest(f"{path} is not valid YAML: {broken}") from broken

    return [
        document
        for document in loaded
        if isinstance(document, dict) and _identity_of(document) is not None
    ]


def _identity_of(document: dict[str, Any]) -> Identity | None:
    """What this document is, or `None` when it is not a Kubernetes object.

    `apiVersion` and `kind` together are the API's own rule for what an object
    is. A `values.yaml` has neither, and reviewing one as a manifest produces
    findings about fields it was never going to have.
    """
    kind = document.get("kind")
    if not document.get("apiVersion") or not isinstance(kind, str) or not kind:
        return None

    metadata = document.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        return None

    namespace = metadata.get("namespace")
    return Identity(
        kind=kind, name=name, namespace=namespace if isinstance(namespace, str) else None
    )


def pair(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[Change]:
    """Match two sets of documents by identity.

    Sorted by identity so the output does not depend on document order in the
    file - the same reason `core/orchestrator/hypotheses.py` sorts its ranking.
    A caller comparing two runs of this must get the same list.
    """
    keyed_before = {_require(document): document for document in before}
    keyed_after = {_require(document): document for document in after}

    return [
        Change(
            identity=identity,
            before=keyed_before.get(identity),
            after=keyed_after.get(identity),
        )
        for identity in sorted(keyed_before.keys() | keyed_after.keys(), key=str)
    ]


def _require(document: dict[str, Any]) -> Identity:
    identity = _identity_of(document)
    if identity is None:  # pragma: no cover - documents() filters these out
        raise UnreadableManifest("a document reached pairing without an identity")
    return identity


def extract(files: list[tuple[str, str | None, str | None]]) -> Extraction:
    """Turn `(path, before_text, after_text)` triples into reviewable changes.

    `None` for a side means the file did not exist at that revision - an added
    file has no before, a deleted one has no after. That is not an error and it
    is what makes a whole-file deletion review as the removal of everything in
    it.

    A file that fails to parse is recorded in `unreadable` rather than raised
    on. One bad file in twenty must not cost the review of the other nineteen,
    and a caller that ignores the list is a caller reporting a clean run over
    files nothing read - which is why `complete` exists to be checked.
    """
    extraction = Extraction()

    for path, before_text, after_text in files:
        try:
            before = documents(before_text, path=path) if before_text is not None else []
            after = documents(after_text, path=path) if after_text is not None else []
        except UnreadableManifest:
            extraction.unreadable.append(path)
            continue
        extraction.changes.extend(pair(before, after))

    return extraction
