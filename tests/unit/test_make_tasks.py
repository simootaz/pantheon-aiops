"""The Makefile recipes that used to be shell, now that they are testable.

`make help`'s `grep | sed | awk` pipeline had never been exercised by anything.
Neither had `[ -f .env ] || cp`, nor the four `rm -rf` lines. They were shell,
so they were untestable, so nobody knew they only worked on Linux.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.mechanism import read_mechanism
from tooling.make_tasks import clean, ensure_env, main, render_help

MAKEFILE_SAMPLE = """\
## help: list every target
help:
\t@uv run python -m tooling.make_tasks help

# not a help line
## test: run the suite
test:
\t@uv run pytest
"""


# --- help ---------------------------------------------------------------------------


def test_only_double_hash_lines_become_rows() -> None:
    """`make help` renders one row per `## name: text` and parses nothing else."""
    rendered = render_help(MAKEFILE_SAMPLE)

    assert rendered.count("\n") == 1, "a comment that is not a help line became a row"
    assert "help" in rendered and "test" in rendered
    assert "not a help line" not in rendered


def test_the_description_survives_a_colon_in_it() -> None:
    """`## sim: run a scenario (SCENARIO=name)` has a colon in the description
    on some lines, and splitting on every colon would truncate them."""
    rendered = render_help("## sim: run a scenario, e.g. make sim SCENARIO=x:y\n")

    assert "SCENARIO=x:y" in rendered


def test_a_makefile_with_no_help_lines_renders_nothing() -> None:
    """Empty, not a crash. A Makefile mid-edit is not an error worth stopping
    somebody who typed `make help` to find out what exists."""
    assert render_help("all:\n\techo hi\n") == ""


# --- ensure-env ---------------------------------------------------------------------


def test_the_template_is_copied_when_there_is_no_env(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    target = tmp_path / ".env"

    assert ensure_env(target, template) is True
    assert read_mechanism(target) == read_mechanism(template)


def test_an_existing_env_is_never_overwritten(tmp_path: Path) -> None:
    """The file it would clobber holds somebody's local passwords, and `make up`
    is a command people run without thinking about it."""
    template = tmp_path / ".env.example"
    template.write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text("POSTGRES_PASSWORD=mine\n", encoding="utf-8")

    assert ensure_env(target, template) is False
    assert "mine" in read_mechanism(target), "the local passwords were clobbered"


def test_a_missing_template_is_reported_rather_than_creating_an_empty_env(
    tmp_path: Path,
) -> None:
    """An empty `.env` would let `make up` start a stack with no passwords, and
    the failure would arrive as containers refusing to authenticate."""
    with pytest.raises(FileNotFoundError, match="is missing"):
        ensure_env(tmp_path / ".env", tmp_path / "gone.example")


# --- clean --------------------------------------------------------------------------


def test_named_artefacts_are_removed(tmp_path: Path) -> None:
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / "htmlcov").mkdir()
    (tmp_path / "coverage.xml").write_text("<x/>", encoding="utf-8")

    removed = clean(tmp_path)

    assert not (tmp_path / ".mypy_cache").exists()
    assert not (tmp_path / "coverage.xml").exists()
    assert set(removed) >= {".mypy_cache", "htmlcov", "coverage.xml"}


def test_pycache_is_removed_wherever_it_is(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "__pycache__"
    nested.mkdir(parents=True)
    (nested / "x.pyc").write_bytes(b"\x00")

    clean(tmp_path)

    assert not nested.exists()
    assert (tmp_path / "a" / "b").exists(), "only the cache directory should go"


def test_source_is_not_touched(tmp_path: Path) -> None:
    """The control. A `clean` that removed everything would pass every test
    above and be a very expensive mistake."""
    keep = tmp_path / "core" / "config.py"
    keep.parent.mkdir(parents=True)
    keep.write_text("SETTINGS = 1\n", encoding="utf-8")

    clean(tmp_path)

    assert "SETTINGS = 1" in read_mechanism(keep)


def test_cleaning_an_already_clean_tree_removes_nothing(tmp_path: Path) -> None:
    assert clean(tmp_path) == []


def test_nothing_outside_the_root_is_deleted(tmp_path: Path) -> None:
    """A path escaping through a symlink or a `..` name would make this a
    recursive delete somewhere nobody was looking. The shell version had no such
    check, because writing one in `find` is impractical.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me", encoding="utf-8")

    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "__pycache__").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege on Windows
        pytest.skip("this platform will not create a directory symlink without privilege")

    clean(root)

    assert (outside / "precious.txt").exists(), "clean followed a symlink out of the repository"


# --- the entry point ------------------------------------------------------------------


def test_an_unknown_task_is_refused_rather_than_silently_doing_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A typo in a recipe that exited 0 would make the target report success
    having done nothing - which is the whole failure mode this repository keeps
    finding."""
    assert main(["make_tasks", "clen"]) == 2
    assert "unknown task" in capsys.readouterr().err


def test_no_task_at_all_is_also_refused() -> None:
    assert main(["make_tasks"]) == 2


def test_help_prints_the_real_makefile(capsys: pytest.CaptureFixture[str]) -> None:
    """End to end against the file `make help` actually reads."""
    assert main(["make_tasks", "help"]) == 0

    printed = capsys.readouterr().out
    assert "test-sim" in printed and "codegen" in printed
