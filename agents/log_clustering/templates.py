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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
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

#: How many times a field must actually CHANGE before its direction means
#: anything. Two changes agreeing is a coin landing the same way twice. A
#: constant never changes and so is never called a sequence, which is right - a
#: field with one value is the purest category there is.
MIN_ORDER_CHANGES = 8

#: The fraction of adjacent pairs that must move consistently before a field is
#: called a sequence. High, because the alternative reading - a category whose
#: values happen to be interleaved by chance - sits near one half and never
#: approaches this. Measured: `ts` reaches ~0.99 and `status` ~0.67.
ORDER_FRACTION = 0.95

#: How many example lines a template keeps. Enough to read, not enough to make
#: the result a copy of the window.
EXAMPLES_KEPT = 3

#: Splits a text line into tokens. Whitespace only - deliberately not a
#: punctuation-aware split, which would be another encoded assumption about
#: what logs look like.
_TOKENS = re.compile(r"\s+")

#: An embedded value needs at least this many lines to be considered a stack.
#: What makes it one is the shared punctuation skeleton below, not a keyword.
MIN_TRACE_FRAMES = 2

#: What varies between two throws of the same fault: line numbers, and pointers.
#: Decimal runs and `0x`-prefixed hex, because a decimal-only rule left Go's
#: `main.process(0xa)` and `main.process(0xb)` as separate faults - forty throws
#: of one bug reported as forty. Not exhaustive: a bare hex address with no `0x`
#: is indistinguishable from a word and is left alone.
_VARIANT = re.compile(r"0[xX][0-9a-fA-F]+|\d+")


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
    #: Fields the ordering rule identified as clocks or counters, per shape.
    #: Empty across the board is a signal in itself: either these logs carry no
    #: timestamp, or the caller did not pass the lines in emission order.
    sequence_fields: dict[str, list[str]] = field(default_factory=dict)

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


def _ordered(values: list[str]) -> bool:
    """True when a field only ever moves one way through the window.

    THE RULE CARDINALITY ALONE CANNOT REPLACE
    -------------------------------------------
    A clock is a variable field however few values it takes. Measured on a
    compressed simulator run, `ts` took five distinct values across 5000 lines -
    comfortably under any cardinality cap - and was templated as a category. The
    result was 298 templates from ten source templates, and a novelty check that
    reported sixty new patterns in a window with no fault in it.

    Cardinality asks how many values a field has. This asks whether they are a
    *sequence*, which is what separates a timestamp, an offset or a counter from
    a status code. Both are needed: neither alone gets this right.

    Lexicographic, so it holds for ISO-8601 timestamps and zero-padded ids and
    does NOT hold for unpadded numeric counters - `9` sorts after `10`. Stated
    rather than claimed universal; an unpadded counter is caught by cardinality
    instead, since a counter with few values is not a counter.

    A FRACTION OF ADJACENT PAIRS, NOT GLOBAL SORTEDNESS
    -----------------------------------------------------
    The first version asked whether the whole list was sorted. It caught nothing,
    because a window read out of Loki is several streams concatenated and the
    clock restarts at every boundary. Global sortedness is a property of one
    source; a corpus assembled from many has no single order.

    Counting adjacent pairs survives that - a handful of boundary inversions
    among thousands of pairs cannot drag the fraction below the threshold, while
    a genuinely interleaved category sits near half and never approaches it.

    TIES ARE EXCLUDED, WHICH IS THE WHOLE OF IT
    ---------------------------------------------
    Counting every pair made a RARE value look ordered. `status` is 500 three
    times in five thousand lines, so 99.9% of its adjacent pairs are equal and
    "consistently ordered" was satisfied by a field that is the single most
    important discriminator in the window.

    So only pairs where the value CHANGES are counted. A clock changes upward
    every time; a category changes both ways in roughly equal measure whatever
    the mix of its values. That also removes the need for a distinct-value floor
    to exclude constants - a constant has no changes at all.

    THIS REQUIRES `lines` TO BE IN EMISSION ORDER
    -----------------------------------------------
    Stated because it is not free. A window read out of Loki arrives as several
    streams concatenated, and in that arrangement a real clock is only ~80%
    consistent - it runs one way inside a stream and jumps back at every
    boundary. Counting ties hid that: the equal pairs were so numerous they
    carried the fraction over the line, and the rule appeared to work for a
    reason that had nothing to do with time.

    So the caller sorts. Loki stamps every entry with a nanosecond timestamp,
    which is emission order stated by the source rather than inferred from the
    text. `Clustering.sequence_fields` reports what this found, so a caller that
    forgot to sort sees an empty set instead of a quietly worse template set.
    """
    steps = [(left, right) for left, right in pairwise(values) if left != right]
    if len(steps) < MIN_ORDER_CHANGES:
        return False
    rising = sum(1 for left, right in steps if left < right)
    return max(rising, len(steps) - rising) / len(steps) >= ORDER_FRACTION


def _sequence_fields(rows: list[_Parsed]) -> list[str]:
    """Which of this group's fields are clocks or counters. Reported, not hidden."""
    seen: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for key, value in row.fields.items():
            seen[key].append(value)
    return sorted(key for key, values in seen.items() if _ordered(values))


def _stable_fields(rows: list[_Parsed]) -> set[str] | None:
    """Which fields discriminate in this group, or None if it is too small.

    None rather than an empty set: "no field discriminates" and "not enough
    lines to tell" are different facts, and collapsing them is how a refusal
    starts being read as a result.
    """
    if len(rows) < MIN_GROUP_FOR_VARIABILITY:
        return None

    seen: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        for key, value in row.fields.items():
            seen[key].append(value)

    ceiling = max(1.0, VARIABILITY_RATIO * len(rows))
    return {
        key
        for key, values in seen.items()
        if len(set(values)) <= MAX_STABLE_VALUES
        and len(set(values)) <= ceiling
        and not _ordered(values)
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


#: Which fields discriminate, per shape. `None` for a shape whose group was too
#: small to say. Learned once and applied to several windows - see `learn`.
Classification = dict[str, set[str] | None]


def learn(lines: list[str]) -> Classification:
    """Work out which fields discriminate, so several windows can share it.

    WHY THIS IS SEPARABLE FROM CLUSTERING
    ---------------------------------------
    Variability is inferred from a group, so the group's SIZE changes the
    inference. Measured: during `bad_deploy_5xx` there are many `request failed`
    lines, so `path` and `status` go high-cardinality and are masked; during
    `disk_pressure` there are a handful, so the same two stay stable and split
    that one event into twenty-six templates.

    The same event, templated two ways, according to how much of it a window
    happened to hold. Comparing those two windows for "templates present in one
    and absent from the other" then measures fault intensity and reports it as
    novelty - which is what the measurement showed: twenty-six novel templates
    for `disk_pressure`, every one of them a `request failed` variant, none of
    them anything to do with a disk.

    So the classification is learned ONCE over the pooled corpus and applied to
    every window compared against it. Two windows are then comparable by
    construction rather than by luck.
    """
    groups: dict[str, list[_Parsed]] = defaultdict(list)
    for line in lines:
        row = _parse(line)
        if row is not None:
            groups[row.shape].append(row)
    return {shape: _stable_fields(rows) for shape, rows in groups.items()}


def cluster(lines: list[str], classification: Classification | None = None) -> Clustering:
    """Reduce a window of log lines to templates with counts.

    Two passes, because variability cannot be known from one line. The first
    groups by shape and counts distinct values per field; the second assigns
    each line to a template. A streaming one-pass version would have to guess at
    the first line what the thousandth will show.

    Pass `classification` - from `learn()` over a pooled corpus - when the result
    will be compared with another window. Without it each window infers its own,
    and two windows holding different amounts of the same event template it
    differently.
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

    sequences: dict[str, list[str]] = {}
    for shape, rows in groups.items():
        stable = _stable_fields(rows) if classification is None else classification.get(shape)
        found = _sequence_fields(rows)
        if found:
            sequences[shape] = found
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

    return Clustering(
        templates=templates,
        lines_seen=len(parsed),
        unparsed=unparsed,
        sequence_fields=sequences,
    )


def compare(incident: list[str], reference: list[str]) -> tuple[Clustering, Clustering]:
    """Cluster two windows under ONE field classification, so they are comparable.

    The only correct way to reach `novel()`. Clustering each window on its own
    and diffing the results measures how much of each event a window held as
    much as it measures what appeared - see `learn()`.
    """
    shared = learn([*reference, *incident])
    return cluster(incident, shared), cluster(reference, shared)


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

    "Look like a stack" means several lines with the same PUNCTUATION SKELETON -
    the non-alphanumeric characters in order, with the words and numbers removed.
    Frames are structurally repetitive whatever language produced them; prose
    wrapped across lines is not.

    The first version of this asked for a shared leading *token*, which is true
    of `at com.acme...` and of `File "...", line N` and false of Go's
    `main.process(0x0)`. It was written with a docstring claiming to name no
    language, and it named two by implication. Its own test caught it.

    Not precise: a multi-line SQL statement has a repetitive skeleton too and
    would be reported. Said plainly rather than dressed up - `header` is kept
    verbatim so a reader can see what was matched.
    """
    found: list[tuple[str, list[str]]] = []
    for key, value in sorted(row.fields.items()):
        if "\n" not in value:
            continue
        pieces = [piece.strip() for piece in value.split("\n") if piece.strip()]
        if len(pieces) < MIN_TRACE_FRAMES:
            continue
        skeletons = [_skeleton(piece) for piece in pieces]
        common, hits = Counter(skeletons).most_common(1)[0]
        # A non-empty skeleton shared by at least half the lines. Non-empty
        # matters: prose wrapped across lines has no punctuation at all, and
        # every line of it shares that emptiness.
        if not common or hits * 2 < len(pieces):
            continue
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
            signature = "|".join(_VARIANT.sub("<n>", frame) for frame in frames)
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


def _skeleton(text: str) -> str:
    """The punctuation of a line, with words and numbers removed."""
    return "".join(char for char in text if not char.isalnum() and not char.isspace())


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
