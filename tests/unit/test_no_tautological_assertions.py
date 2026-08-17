"""A guard for the rule the whole repository is built on.

> If you have not seen it red, you have not tested it.

Fifteen branches into a project with that as its central rule, an assertion
ending in `or True` still got written — an assertion that cannot fail, in a test
suite whose entire job is to fail when something is wrong. Vigilance did not
catch it; a failing test did, and only by accident.

So the rule now has a guard of its own.

WHAT RUFF ALREADY COVERS
------------------------
`SIM222` catches `... or True` and `SIM221` catches `x or not x`, and both are
in the selected rule set. They are re-checked here anyway, cheaply, so this
guard does not silently weaken if the ruff configuration changes.

Ruff does **not** catch `assert True`, `assert 1`, `assert "literal"`, or a test
whose body is `pass`. Those are this module's real work.

A NOTE ON HOW THE ORIGINAL ESCAPED
----------------------------------
Ruff would have flagged it. It was missed because the iteration loop ran
`ruff check --fix -q … >/dev/null 2>&1` and discarded the output. A linter whose
output is thrown away is not a linter, which is the same class of mistake as a
guard that only ever passes — and the reason this check runs inside pytest,
where its result cannot be redirected away.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = REPO_ROOT / "tests"

#: Names that count as asserting something, beyond the `assert` statement.
ASSERTION_CALLS = frozenset({"raises", "fail", "skip", "xfail", "warns", "approx", "exit"})


def _is_truthy_constant(node: ast.expr) -> bool:
    """True for a literal that is always truthy: True, 1, "x", [1], {"a": 1}."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    return False


def _same_source(left: ast.expr, right: ast.expr) -> bool:
    return ast.dump(left) == ast.dump(right)


def tautology_reason(test: ast.expr) -> str | None:
    """Why `assert <test>` can never fail, or None if it can."""
    if _is_truthy_constant(test):
        return f"asserts a constant that is always truthy: {ast.unparse(test)}"

    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        for value in test.values:
            if _is_truthy_constant(value):
                return f"`or {ast.unparse(value)}` makes the whole assertion always true"
        # x or not x, in either order
        for index, left in enumerate(test.values):
            for right in test.values[index + 1 :]:
                if _negates(right, left) or _negates(left, right):
                    return f"`{ast.unparse(test)}` is a tautology"

    if (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.left, ast.Constant)
        and isinstance(test.comparators[0], ast.Constant)
    ):
        return f"compares two constants: {ast.unparse(test)}"

    return None


def _negates(candidate: ast.expr, other: ast.expr) -> bool:
    """True when `candidate` is exactly `not other`."""
    return (
        isinstance(candidate, ast.UnaryOp)
        and isinstance(candidate.op, ast.Not)
        and _same_source(candidate.operand, other)
    )


def _is_placeholder(statement: ast.stmt) -> bool:
    """A docstring, `pass`, or `...` — a body that does nothing."""
    if isinstance(statement, ast.Pass):
        return True
    return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)


def _asserts_something(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name in ASSERTION_CALLS:
                return True
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    call = item.context_expr.func
                    if isinstance(call, ast.Attribute) and call.attr in ASSERTION_CALLS:
                        return True
    return False


def _test_files() -> list[Path]:
    return sorted(TESTS.rglob("test_*.py"))


# ---------------------------------------------------------------------------
# the detector, pinned in both directions
# ---------------------------------------------------------------------------


def _reason_for(source: str) -> str | None:
    statement = ast.parse(source).body[0]
    assert isinstance(statement, ast.Assert)
    return tautology_reason(statement.test)


def test_the_detector_catches_every_pattern() -> None:
    """Each of these is an assertion that cannot fail."""
    for source in (
        "assert True",
        "assert 1",
        "assert 'nonempty'",
        "assert [1]",
        "assert {'a': 1}",
        "assert x == 1 or True",
        "assert x or not x",
        "assert not x or x",
        "assert 1 == 1",
    ):
        assert _reason_for(source) is not None, f"detector missed: {source}"


def test_the_detector_permits_real_assertions() -> None:
    """And does not fire on assertions that can genuinely fail."""
    for source in (
        "assert x",
        "assert x == 1",
        "assert not offenders, 'message'",
        "assert x is True",
        "assert result.count > 0",
        "assert x or y",
        "assert []",
        "assert 0",
    ):
        assert _reason_for(source) is None, f"detector false-positived: {source}"


# ---------------------------------------------------------------------------
# applied to the suite
# ---------------------------------------------------------------------------


def test_no_test_contains_an_unfailable_assertion() -> None:
    """An assertion that cannot fail is worse than no assertion.

    No assertion is visibly missing. One that cannot fail looks like coverage.
    """
    offenders: list[str] = []

    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            if reason := tautology_reason(node.test):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {reason}")

    assert not offenders, "assertions that can never fail:\n  " + "\n  ".join(offenders)


def test_no_test_body_is_empty() -> None:
    """A test that runs nothing reports success for doing nothing."""
    offenders: list[str] = []

    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if all(_is_placeholder(statement) for statement in node.body):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name}")

    assert not offenders, "test functions with an empty body:\n  " + "\n  ".join(offenders)


def test_every_test_asserts_something() -> None:
    """A test with no assertion mechanism at all passes by reaching the end.

    `pytest.raises`, `pytest.fail`, `pytest.skip` and `pytest.warns` all count -
    the point is that the test has a way to report failure, not that it uses
    the `assert` keyword.
    """
    offenders: list[str] = []

    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if not _asserts_something(node):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name}")

    assert not offenders, "test functions that assert nothing:\n  " + "\n  ".join(offenders)


def test_ruff_still_covers_the_two_patterns_it_owns() -> None:
    """SIM221 and SIM222 must stay selected, or this guard silently widens."""
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    selected = config["tool"]["ruff"]["lint"]["select"]
    assert "SIM" in selected, (
        "ruff's SIM rules were deselected; SIM221/SIM222 catch `x or not x` and "
        "`... or True` at lint time, before pytest ever runs"
    )
