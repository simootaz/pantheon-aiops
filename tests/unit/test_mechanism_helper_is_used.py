"""No test module reads a file except through `tests.mechanism`.

The doc-satisfies-mechanism bug has been fixed five times in this repository and
kept returning, because the fix lived in one helper while the raw read stayed
the obvious thing to type. A convention that has to be remembered is not a fix.
This makes it structural: reading a file any other way fails the build.

`read_verbatim(path, why=...)` is the escape hatch, and it costs one argument
explaining itself — enough friction to make the choice deliberate.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.mechanism import read_verbatim

TESTS = Path(__file__).resolve().parents[1]
#: The helper itself must read files; that is its job.
EXEMPT = {"mechanism.py"}
#: Lives under tests/ but is a tool, not a test module.
TOOLS = {"coverage_floor.py"}

READERS = {"read_text", "read_bytes", "open"}

OFFENDING_SOURCE = "from pathlib import Path\nPath('x').read_text()\n"
CLEAN_SOURCE = "from tests.mechanism import read_mechanism\nread_mechanism(p)\n"


def modules() -> list[Path]:
    return sorted(
        path
        for path in TESTS.rglob("*.py")
        if path.name not in EXEMPT | TOOLS and not path.name.startswith("__")
    )


def raw_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Every call that pulls file content in without going through the helper."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in READERS:
            found.append((node.lineno, f".{func.attr}()"))
        elif isinstance(func, ast.Name) and func.id == "open":
            found.append((node.lineno, "open()"))
    return found


@pytest.mark.parametrize("module", modules(), ids=lambda p: p.name)
def test_no_test_module_reads_a_file_directly(module: Path) -> None:
    """Route every read through tests.mechanism, so stripping is the default."""
    source = read_verbatim(module, why="an AST needs the source exactly as written")
    offenders = raw_reads(ast.parse(source))
    assert not offenders, (
        f"{module.relative_to(TESTS.parent)} reads files directly at "
        + ", ".join(f"line {line} ({call})" for line, call in offenders)
        + ". Use tests.mechanism.read_mechanism(path), or read_verbatim(path, "
        "why=...) when the comments are genuinely what is being asserted."
    )


def test_the_scanner_sees_a_direct_read_and_ignores_a_helper_call() -> None:
    """Both directions, without waiting for someone to plant one.

    The scanner is the whole guard, so it is exercised on source that does
    exactly what it is meant to catch, and on source that does not.
    """
    assert raw_reads(ast.parse(OFFENDING_SOURCE)), "the scanner cannot see a direct read"
    for source in ("open('x')", "p.open()", "p.read_bytes()"):
        assert raw_reads(ast.parse(source)), f"the scanner cannot see {source}"

    assert not raw_reads(ast.parse(CLEAN_SOURCE)), "the scanner fires on a helper call"


def test_read_verbatim_demands_a_reason() -> None:
    """The escape hatch has to cost something, or it becomes the default."""
    with pytest.raises(ValueError, match="reason"):
        read_verbatim(Path(__file__), why="   ")
