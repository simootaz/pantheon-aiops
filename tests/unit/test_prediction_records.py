"""Every predictions directory is complete, and committed.

`55b0360` was committed on a feature branch, was not an ancestor of the merge,
and was one branch deletion from gone. A commit existing locally and a commit
surviving a merge are different facts.

WHY THE DIRECTORIES ARE DISCOVERED RATHER THAN NAMED
------------------------------------------------------
This used to check `docs/argus-predictions` by name. The second agent to need
prediction records - Lethe - would have got a directory with no guard over it,
and an unguarded directory looks exactly like a guarded one that passes.

Same family as an exemption naming a gate that does not run its module: the
check had a subject, was green, and the new thing simply was not it. So the
directories are found by pattern, and adding `docs/<agent>-predictions/` brings
it under every check below without anyone remembering to.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.mechanism import read_data

REPO_ROOT = Path(__file__).resolve().parents[2]


def directories() -> list[Path]:
    """Every predictions directory, found rather than listed.

    The one missing from a hand-maintained list is the one nobody checked.
    """
    found = sorted(path for path in (REPO_ROOT / "docs").glob("*-predictions") if path.is_dir())
    assert found, "no predictions directory found; every check here would pass vacuously"
    return found


def _tracked(directory: Path) -> set[str]:
    """Paths git actually has, rather than paths present on this disk."""
    result = subprocess.run(
        ["git", "ls-files", directory.relative_to(REPO_ROOT).as_posix()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_every_prediction_file_is_tracked() -> None:
    """Present on disk is not the same as in the branch.

    The ordering predictions were written, committed, and then absent from
    `develop` - the commit lived on a feature branch that the merge did not
    carry. Nothing noticed, because the file was still sitting in the working
    tree where it had always been.
    """
    for directory in directories():
        tracked = _tracked(directory)
        on_disk = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        }
        untracked = sorted(on_disk - tracked)
        assert not untracked, (
            f"prediction records present on disk but not tracked by git: {untracked}. "
            "A file in the working tree is one branch switch from gone."
        )
        assert tracked, f"{directory.name} is tracked by nothing at all"


def test_every_prediction_carries_its_scoring() -> None:
    """A prediction without its committed scoring is half a record.

    The point of writing numbers first is that a miss stays visible. A file that
    states what was expected and never says what happened loses exactly the
    half that makes the practice worth anything.
    """
    unscored: list[str] = []
    for directory in directories():
        for path in sorted(directory.glob("[0-9][0-9]-*.md")):
            body = read_data(path)
            if not re.search(r"^#+ .*Result", body, re.MULTILINE | re.IGNORECASE):
                unscored.append(f"{directory.name}/{path.name}")

    assert not unscored, (
        f"prediction files with no result section: {unscored}. Add the scoring - "
        "hit or miss per prediction - or say plainly that the measurement is "
        "still pending and why."
    )


def test_pending_records_say_so_in_both_places() -> None:
    """An unscored prediction is a state, not an omission.

    A record committed before its measurement is correct practice. What is not
    correct is an index claiming a result the file does not have, or a file
    scored while the index still reads pending - either way the reader is told
    something the directory does not support.
    """
    for directory in directories():
        index = read_data(directory / "README.md")
        for path in sorted(directory.glob("[0-9][0-9]-*.md")):
            body = read_data(path)
            pending_in_file = bool(
                re.search(r"^#+ .*Result.*PENDING", body, re.MULTILINE | re.IGNORECASE)
            )
            row = next((line for line in index.splitlines() if f"]({path.name})" in line), None)
            assert row is not None, f"{directory.name}/{path.name} is not in the index"
            pending_in_index = "pending" in row.lower()

            assert pending_in_file == pending_in_index, (
                f"{directory.name}/{path.name}: the file says "
                f"pending={pending_in_file} and the index says "
                f"pending={pending_in_index}. Scoring a record means updating both."
            )


def test_the_index_lists_every_record_and_no_others() -> None:
    """An index that drifts from its directory is worse than no index."""
    for directory in directories():
        index = read_data(directory / "README.md")
        linked = set(re.findall(r"\]\((\d\d-[a-z0-9-]+\.md)\)", index))
        actual = {path.name for path in directory.glob("[0-9][0-9]-*.md")}

        assert linked == actual, (
            f"{directory.name}: the index and the directory disagree. Only in the "
            f"index: {sorted(linked - actual)}. Only on disk: {sorted(actual - linked)}"
        )

        numbers = sorted(int(name[:2]) for name in actual)
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"{directory.name}: the record numbering has a gap: {numbers}. A missing "
            "number is how a deleted record hides - the remaining files still agree "
            "with an index that was edited to match them."
        )


def _scored(directory: Path) -> list[str]:
    """Records in this directory that claim a result rather than pending one."""
    scored: list[str] = []
    for path in sorted(directory.glob("[0-9][0-9]-*.md")):
        body = read_data(path)
        if not re.search(r"^#+ .*Result.*PENDING", body, re.MULTILINE | re.IGNORECASE):
            scored.append(path.name)
    return scored


def test_the_cited_measurements_exist() -> None:
    """A scoring that cites data nobody can open is an assertion, not a record.

    The requirement is tied to a SCORING, not to the directory existing. A
    directory whose every record is still pending has correctly not measured
    anything yet - predictions are committed before the measurement runs, so
    demanding data there would forbid the practice this whole directory is for.

    The moment one record is scored, its data has to be present.
    """
    for directory in directories():
        data = directory / "data"
        assert data.is_dir(), f"{directory.name}/data is gone"

        index = read_data(data / "README.md")
        cited = set(re.findall(r"`([a-z0-9-]+\.json)`", index))
        present = {path.name for path in data.glob("*.json")}
        assert cited <= present, f"{directory.name}: cited but missing: {sorted(cited - present)}"

        scored = _scored(directory)
        assert present or not scored, (
            f"{directory.name} commits no measurements, but {scored} claim a "
            "result. A scoring with no data behind it is an assertion."
        )
