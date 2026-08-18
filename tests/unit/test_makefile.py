"""Guards over the Makefile itself.

The Makefile is the documented way to run everything, and until GNU Make was
installed on a developer machine every target had only ever been exercised by
running its *body* by hand. Three defects were sitting in it, all invisible to
that: a target missing from `.PHONY`, a two-line `##` comment that garbled
`make help`, and a default `SPEED` no tick size could deliver.

These are cheap parses, not invocations — running the targets takes minutes and
needs Docker, Go and pnpm. CI runs the real thing; this catches the shapes.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path

from simulator.runner import DEFAULT_TICK_SECONDS, max_honest_speed
from tests.mechanism import read_verbatim

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
BODY = read_verbatim(
    MAKEFILE, why="the `## name: text` lines make help parses are themselves comments"
)

#: A target definition: a name at the start of a line, followed by a colon.
#: Excludes variable assignments (`NAME :=`) and `.PHONY`-style directives.
TARGET = re.compile(r"^(?!\.)([a-zA-Z][a-zA-Z0-9_-]*):(?!=)", re.MULTILINE)
#: The help formatter's input: "## name: description".
HELP_LINE = re.compile(r"^## ([^:]+):(.*)$", re.MULTILINE)


def targets() -> set[str]:
    return set(TARGET.findall(BODY))


def phony() -> set[str]:
    """Everything listed on the .PHONY line, backslash continuations included.

    Continuations are joined across the whole file first. Trying to express
    "line, optionally continued" in one pattern is where this went wrong the
    first time: `[^\\n]` happily eats the trailing backslash, so the alternation
    that was supposed to hop the newline never matched, and the guard reported
    six targets missing that were listed on the second line all along.
    """
    joined = re.sub(r"\\\n\s*", " ", BODY)
    match = re.search(r"^\.PHONY:([^\n]*)", joined, re.MULTILINE)
    assert match, "the Makefile declares no .PHONY at all"
    return set(match.group(1).split())


def test_every_target_is_declared_phony() -> None:
    """A target sharing a name with a file silently stops running.

    `test-sim` was added without being listed, so a file or directory called
    `test-sim` would have made `make test-sim` a no-op reporting success.
    """
    missing = sorted(targets() - phony())
    assert not missing, f"targets missing from .PHONY: {missing}"


def test_phony_does_not_list_targets_that_do_not_exist() -> None:
    """The other direction: a stale .PHONY entry means a target was renamed."""
    stale = sorted(phony() - targets())
    assert not stale, f".PHONY lists targets that no longer exist: {stale}"


def test_every_target_has_exactly_one_help_line() -> None:
    """`make help` prints one row per `## name: text`, and parses nothing else.

    A second `## ` line under a target became a row with an empty name and the
    continuation text in the description column.
    """
    documented = [name.strip() for name, _text in HELP_LINE.findall(BODY)]
    duplicated = sorted({name for name in documented if documented.count(name) > 1})
    assert not duplicated, f"more than one ## line for: {duplicated}"

    unknown = sorted(set(documented) - targets())
    assert not unknown, (
        f"## lines that name no target: {unknown}. `make help` renders these as "
        "rows with nothing in the target column."
    )

    undocumented = sorted(targets() - set(documented))
    assert not undocumented, f"targets with no ## line, invisible to make help: {undocumented}"


def test_no_stray_double_hash_lines_reach_the_help_formatter() -> None:
    """Any `## ` line without a colon would print as a nameless row."""
    for line in BODY.splitlines():
        if line.startswith("## "):
            assert ":" in line, f"## line with no target name reaches make help: {line!r}"


def test_the_default_sim_speed_is_one_the_runner_can_deliver() -> None:
    """A default above the ceiling makes the fell-behind warning fire always.

    The warning is real and worth keeping; firing it on every ordinary run is
    how it gets tuned out. Tied to `max_honest_speed` so the two cannot drift
    apart silently.
    """
    match = re.search(r"--speed \$\(or \$\(SPEED\),([0-9.]+)\)", BODY)
    assert match, "the sim target no longer has a default speed to check"

    default = float(match.group(1))
    ceiling = max_honest_speed(DEFAULT_TICK_SECONDS)
    assert default <= ceiling, (
        f"make sim defaults to {default:.0f}x, above the {ceiling:.0f}x that a "
        f"{DEFAULT_TICK_SECONDS:.0f}s tick can deliver. Every default run would "
        "report falling behind."
    )


def recipe_for(target: str) -> str:
    """The tab-indented command lines of a target, comments excluded.

    Splitting the file on `"<target>:"` is the obvious approach and it is wrong:
    the `## <target>: description` help line matches first, so the "recipe" comes
    back containing the comment block. Every explanatory comment mentioning the
    mechanism then satisfies a check meant to prove the mechanism is *there* —
    the failure mode CONTRIBUTING names, reproduced while writing a guard
    against a different one.

    So: find the target definition at the start of a line, take only the lines
    beginning with a tab, and drop `#` comments among them.
    """
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n", BODY, re.MULTILINE)
    assert match, f"no target named {target!r}"

    lines = []
    for line in BODY[match.end() :].splitlines():
        if not line.startswith("\t"):
            break
        stripped = line.lstrip("\t").lstrip()
        if not stripped.startswith("#"):
            lines.append(line)
    return "\n".join(lines)


def test_test_sim_requires_the_stack_rather_than_skipping() -> None:
    """A skipped gate is reported as a pass, and this one exists to assert data.

    `make test-sim` skipped all nine tests and exited 0 on a machine where Loki
    was briefly unready. Without the env var it would do so again.
    """
    recipe = recipe_for("test-sim")
    assert "PANTHEON_REQUIRE_STACK" in recipe, (
        "make test-sim does not set PANTHEON_REQUIRE_STACK, so an unreachable "
        f"stack makes the whole gate skip and exit 0. Recipe:\n{recipe}"
    )


def test_the_integration_mark_is_deselected_by_the_fast_suite() -> None:
    """`make test` must stay runnable without Docker."""
    recipe = recipe_for("test")
    assert "not integration" in recipe, (
        "make test no longer deselects the integration mark, so the fast suite "
        f"now needs a live observability stack. Recipe:\n{recipe}"
    )
