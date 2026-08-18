"""Reading files in tests, with comment-stripping as the default.

WHY THIS IS A MODULE AND NOT A CONVENTION
-----------------------------------------
Asserting a substring against a whole file is a trap. `"fail" in body` is true
because a *comment* says "fail closed", so deleting every real `fail()` call
leaves the guard green. The repository has hit this five times:

* three Helm/ArgoCD guards, found in the branch-8 audit;
* `test_test_sim_requires_the_stack_rather_than_skipping`, whose "recipe" was
  extracted by splitting on `test-sim:` — which matched the `## test-sim:` help
  line, so the comment explaining `PANTHEON_REQUIRE_STACK` satisfied a check
  meant to prove the variable was set;
* and the `.PHONY` parser beside it, for a related reason.

Each was fixed locally. The bug kept coming back because the fix lived in one
file while raw `Path.read_text()` stayed the obvious thing to type. So the fix
is now the default, and reading a file verbatim requires saying why.

USE
---
    from tests.mechanism import read_mechanism, read_verbatim

    body = read_mechanism(CHART / "templates" / "validation.yaml")   # scanned
    data = json.loads(read_data(SCHEMA))                              # parsed
    raw = read_verbatim(path, why="the comment banner is the assertion")

`tests/unit/test_mechanism_helper_is_used.py` fails the build if a test module
reads a file any other way.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path

#: Helm/Go template comments: {{/* ... */}} and {{- /* ... */ -}}.
TEMPLATE_COMMENT = re.compile(r"\{\{-?\s*/\*.*?\*/\s*-?\}\}", re.DOTALL)
#: Block comments in Go, TypeScript, JSONC and CSS.
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
#: HTML and Markdown comments.
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
#: Whole-line comments: YAML, shell, Make, Python, TOML, and // for Go/TS.
LINE_COMMENT = re.compile(r"^\s*(#|//)")


def mechanism_only(text: str) -> str:
    """Everything except the prose describing it.

    Removes template, block and HTML comments wherever they appear, then drops
    whole-line `#` and `//` comments. Trailing comments on a line of real code
    are deliberately left alone: stripping them means parsing string literals
    per language, and getting that wrong would silently delete mechanism.
    """
    without_blocks = HTML_COMMENT.sub("", BLOCK_COMMENT.sub("", TEMPLATE_COMMENT.sub("", text)))
    return "\n".join(line for line in without_blocks.splitlines() if not LINE_COMMENT.match(line))


def read_mechanism(path: Path) -> str:
    """Read a file with its comments stripped. The default for any guard."""
    return mechanism_only(path.read_text(encoding="utf-8"))


def read_data(path: Path) -> str:
    """Read a file that is about to be parsed, not scanned.

    JSON, YAML, TOML and Python source are handed to a parser, which discards
    comments itself. Comment-stripping would be pointless there and, for Python,
    actively harmful — it shifts every line number. This is a separate name so
    that "I am parsing this" and "I am scanning this for a mechanism" are
    different statements at the call site rather than the same one.
    """
    return path.read_text(encoding="utf-8")


def read_verbatim(path: Path, *, why: str) -> str:
    """Read a file exactly as written, when the comments are the point.

    `why` is required and unused at runtime. It exists so that opting out of
    comment-stripping is a deliberate, documented act at the call site rather
    than the path of least resistance — which is how the bug kept recurring.
    """
    if not why.strip():
        raise ValueError("read_verbatim needs a reason; that is the whole point of it")
    return path.read_text(encoding="utf-8")
