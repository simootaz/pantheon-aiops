"""Turning a window of log lines into templates, without knowing the logs.

WHAT A TEMPLATE IS HERE
-------------------------
What remains of a line when its *variable* parts are removed. The whole question
is which parts those are, and this module answers it by **measuring the corpus**
rather than by carrying a list of patterns that look variable.

That distinction is the point. A regex list - mask anything that looks like a
timestamp, a uuid, a duration - encodes what its author had seen. It masks an
id format nobody thought of as a constant, and it masks a genuine discriminator
that happens to be numeric. Both failures are silent, and both look like
clustering that worked.

Variability is a property of a field *across a corpus*, so it is counted:

1. Every line is parsed into fields. A JSON object gives named fields; anything
   else gives positional ones, split on whitespace.
2. Lines are grouped by **shape** - the key set for JSON, the token count for
   text. Two lines of different shape are never the same template.
3. Within a shape group, a field is VARIABLE when it takes too many distinct
   values to be a discriminator, and STABLE otherwise.
4. The template is the shape plus the stable fields' values.

WHAT IT REFUSES TO DO
-----------------------
Below `MIN_GROUP_FOR_VARIABILITY` lines, a shape group cannot say which of its
fields discriminate: with three lines, every field looks stable. Rather than
guess - which would produce confident templates from three samples and a
different set from four - the group is templated by **shape alone**, and
`inferred` says so. A caller that treats a shape-only template as a content
template is reading a refusal as a result.

This is also why `cluster()` reports `lines_seen`: a template set from 40 lines
and one from 4000 are different objects, and only the second is worth comparing
against another window.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

#: A field taking more distinct values than this is variable however large the
#: group is. Without it, a 5000-line group would call a 200-value field stable
#: on the ratio alone, and a template keyed on 200 values is 200 templates.
#:
#: Set from measurement - see docs/lethe-predictions/.
MAX_STABLE_VALUES = 8

#: A field is variable when its distinct values exceed this fraction of the
#: group. Catches the small-group case the absolute cap misses: 6 distinct
#: values among 8 lines is an identifier, not a category.
VARIABILITY_RATIO = 0.30

#: Below this many lines, a shape group is templated by shape alone. Three lines
#: make every field look stable, and a template set that changes shape as the
#: fourth line arrives is not a template set.
MIN_GROUP_FOR_VARIABILITY = 12

#: How many example lines a template keeps. Enough to read, not enough to make
#: the result a copy of the window.
EXAMPLES_KEPT = 3

#: Splits a text line into tokens. Whitespace only - deliberately not a
#: punctuation-aware split, which would be another encoded assumption about
#: what logs look like.
_TOKENS = re.compile(r"\s+")

#: An embedded value is a stack trace when it has several lines that begin the
#: same way. Language-agnostic: `at com.acme...` and `File "...", line N` both
#: satisfy it, and neither is named here.
MIN_TRACE_FRAMES = 2


@dataclass(frozen=True)
class Template:
    """One cluster of lines that differ only in their variable parts."""

    signature: str
    rendered: str
    count: int
    inferred: bool
    examples: tuple[str, ...]

    @property
    def shape_only(self) -> bool:
        """True when the group was too small to say which fields discriminate.

        The negation of `inferred`, named positively because that is how a
        caller reads it: this template says a line of this shape occurred, and
        nothing about its content.
        """
        return not self.inferred


@dataclass
class Clustering:
    """Every template in one window, and what the window was."""

    templates: list[Template] = field(default_factory=list)
    lines_seen: int = 0
    unparsed: int = 0

    @property
    def signatures(self) -> set[str]:
        return {template.signature for template in self.templates}

    def by_signature(self) -> dict[str, Template]:
        return {template.signature: template for template in self.templates}


@dataclass(frozen=True)
class _Parsed:
    """One line, reduced to named or positional fields."""

    shape: str
    fields: dict[str, str]
    raw: str


def _parse(line: str) -> _Parsed | None:
    """Split one line into fields, structured if it can be, positional if not.

    JSON structure is used where it exists because it is *stated* rather than
    inferred - a key boundary is not a guess about where a value begins. Text
    lines fall back to whitespace tokens and the same counting applies.
    """
    text = line.strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            body = None
        if isinstance(body, dict):
            flat = {key: _render(value) for key, value in body.items()}
            return _Parsed(shape="json:" + ",".join(sorted(flat)), fields=flat, raw=text)

    tokens = [token for token in _TOKENS.split(text) if token]
    return _Parsed(
        shape=f"text:{len(tokens)}",
        fields={str(index): token for index, token in enumerate(tokens)},
        raw=text,
    )


def _render(value: Any) -> str:
    """A field value as a comparable string.

    Nested structures are rendered whole rather than flattened into more fields:
    flattening would make two lines whose nested object has different keys into
    different shapes, which is a distinction about the *value* masquerading as
    one about the schema.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _stable_fields(rows: list[_Parsed]) -> set[str] | None:
    """Which fields discriminate in this group, or None if it is too small.

    None rather than an empty set: "no field discriminates" and "not enough
    lines to tell" are different facts, and collapsing them is how a refusal
    starts being read as a result.
    """
    if len(rows) < MIN_GROUP_FOR_VARIABILITY:
        return None

    seen: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for key, value in row.fields.items():
            seen[key].add(value)

    ceiling = max(1.0, VARIABILITY_RATIO * len(rows))
    return {
        key
        for key, values in seen.items()
        if len(values) <= MAX_STABLE_VALUES and len(values) <= ceiling
    }


def _signature(row: _Parsed, stable: set[str] | None) -> tuple[str, str]:
    """The identity of this line's template, and a form a human can read."""
    if stable is None:
        return f"{row.shape}|<shape only>", f"{row.shape} (too few lines to template)"

    pairs = sorted((key, row.fields[key]) for key in stable if key in row.fields)
    body = " ".join(f"{key}={value}" for key, value in pairs)
    variable = sorted(key for key in row.fields if key not in stable)
    rendered = body + (" " + " ".join(f"{key}=<*>" for key in variable) if variable else "")
    return f"{row.shape}|{body}", rendered.strip() or row.shape


def cluster(lines: list[str]) -> Clustering:
    """Reduce a window of log lines to templates with counts.

    Two passes, because variability cannot be known from one line. The first
    groups by shape and counts distinct values per field; the second assigns
    each line to a template. A streaming one-pass version would have to guess at
    the first line what the thousandth will show.
    """
    parsed: list[_Parsed] = []
    unparsed = 0
    for line in lines:
        row = _parse(line)
        if row is None:
            unparsed += 1
            continue
        parsed.append(row)

    groups: dict[str, list[_Parsed]] = defaultdict(list)
    for row in parsed:
        groups[row.shape].append(row)

    counts: dict[str, int] = defaultdict(int)
    rendered: dict[str, str] = {}
    inferred: dict[str, bool] = {}
    examples: dict[str, list[str]] = defaultdict(list)

    for shape, rows in groups.items():
        stable = _stable_fields(rows)
        for row in rows:
            signature, human = _signature(row, stable)
            counts[signature] += 1
            rendered.setdefault(signature, human)
            inferred.setdefault(signature, stable is not None)
            if len(examples[signature]) < EXAMPLES_KEPT:
                examples[signature].append(row.raw)
        del shape

    templates = [
        Template(
            signature=signature,
            rendered=rendered[signature],
            count=count,
            inferred=inferred[signature],
            examples=tuple(examples[signature]),
        )
        for signature, count in counts.items()
    ]
    # Descending count, then signature: a stable order matters because these are
    # compared between windows and rendered into Evidence.
    templates.sort(key=lambda template: (-template.count, template.signature))

    return Clustering(templates=templates, lines_seen=len(parsed), unparsed=unparsed)


def novel(incident: Clustering, reference: Clustering) -> list[Template]:
    """Templates present in the incident window and absent from the reference.

    Absence, not rarity. A rate-based rule needs a rate estimate for something
    that occurred zero times, and every way of producing one is an assumption
    about the distribution that nothing here has measured.

    Shape-only templates are excluded. They carry no content, so "this shape is
    new" would fire whenever a window happened to contain a handful of lines of
    a kind the reference had many of - a statement about window size wearing the
    costume of a finding.
    """
    known = reference.signatures
    return [
        template
        for template in incident.templates
        if template.signature not in known and template.inferred
    ]


@dataclass(frozen=True)
class StackTrace:
    """One exception, and the frames under it."""

    signature: str
    header: str
    frames: tuple[str, ...]
    count: int


def _embedded_traces(row: _Parsed) -> list[tuple[str, list[str]]]:
    """Multi-line values inside a line that look like a stack.

    "Look like a stack" means several lines sharing a leading prefix, which is
    true of `at com.acme...` and of `File "...", line N` alike. No language is
    named: a matcher listing Java and Python would silently pass over Go, and
    passing over is indistinguishable from finding nothing.
    """
    found: list[tuple[str, list[str]]] = []
    for key, value in sorted(row.fields.items()):
        if "\n" not in value:
            continue
        pieces = [piece.strip() for piece in value.split("\n") if piece.strip()]
        if len(pieces) < MIN_TRACE_FRAMES:
            continue
        leads = {piece.split()[0] for piece in pieces if piece.split()}
        if len(leads) > max(1, len(pieces) // 2):
            continue  # the lines do not share a frame prefix; not a stack
        found.append((key, pieces))
    return found


def stack_traces(lines: list[str]) -> list[StackTrace]:
    """Pull exception traces out of a window and group them.

    Grouped by the frame list with its numeric parts removed, so the same fault
    at two line numbers is one trace rather than two. The header is kept
    verbatim, because the exception type and message are the part an operator
    reads and the part a summariser must not paraphrase.
    """
    grouped: dict[str, tuple[str, tuple[str, ...], int]] = {}

    for line in lines:
        row = _parse(line)
        if row is None:
            continue
        for _key, pieces in _embedded_traces(row):
            header = _header_for(row, pieces)
            frames = tuple(pieces)
            signature = "|".join(re.sub(r"\d+", "<n>", frame) for frame in frames)
            existing = grouped.get(signature)
            grouped[signature] = (
                existing[0] if existing else header,
                existing[1] if existing else frames,
                (existing[2] if existing else 0) + 1,
            )

    traces = [
        StackTrace(signature=signature, header=header, frames=frames, count=count)
        for signature, (header, frames, count) in grouped.items()
    ]
    traces.sort(key=lambda trace: (-trace.count, trace.signature))
    return traces


def _header_for(row: _Parsed, pieces: list[str]) -> str:
    """What to show above the frames.

    A sibling field naming the exception if one reads that way, else the first
    frame. Chosen by shape - `Type: message` - rather than by field name, since
    `exception`, `error`, `err` and `throwable` are all in use and a name list
    would quietly return the wrong one on the fifth spelling.
    """
    for key, value in sorted(row.fields.items()):
        if "\n" in value:
            continue
        if ": " in value and value.split(":", 1)[0].strip() and " " not in value.split(":", 1)[0]:
            del key
            return value
    return pieces[0]
