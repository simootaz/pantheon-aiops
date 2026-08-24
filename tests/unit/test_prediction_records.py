"""The predictions directory is complete, and committed.

`55b0360` was committed on a feature branch, was not an ancestor of the merge,
and was one branch deletion from gone. A commit existing locally and a commit
surviving a merge are different facts.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.mechanism import read_data

REPO_ROOT = Path(__file__).resolve().parents[2]
PREDICTIONS = REPO_ROOT / "docs" / "argus-predictions"


def _tracked() -> set[str]:
    """Paths git actually has, rather than paths present on this disk."""
    result = subprocess.run(
        ["git", "ls-files", "docs/argus-predictions"],
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
    tracked = _tracked()
    on_disk = {
        path.relative_to(REPO_ROOT).as_posix() for path in PREDICTIONS.rglob("*") if path.is_file()
    }
    untracked = sorted(on_disk - tracked)
    assert not untracked, (
        f"prediction records present on disk but not tracked by git: {untracked}. "
        "A file in the working tree is one branch switch from gone."
    )
    assert len(tracked) >= 6, f"only {len(tracked)} prediction records tracked; expected the set"


def test_every_prediction_carries_its_scoring() -> None:
    """A prediction without its committed scoring is half a record.

    The point of writing numbers first is that a miss stays visible. A file that
    states what was expected and never says what happened loses exactly the
    half that makes the practice worth anything.
    """
    unscored: list[str] = []
    for path in sorted(PREDICTIONS.glob("[0-9][0-9]-*.md")):
        body = read_data(path)
        if not re.search(r"^#+ .*Result", body, re.MULTILINE | re.IGNORECASE):
            unscored.append(path.name)

    assert not unscored, (
        f"prediction files with no result section: {unscored}. Add the scoring - "
        "hit or miss per prediction - or say plainly that the measurement is "
        "still pending and why."
    )


def test_the_index_lists_every_record_and_no_others() -> None:
    """An index that drifts from its directory is worse than no index."""
    index = read_data(PREDICTIONS / "README.md")
    linked = set(re.findall(r"\]\((\d\d-[a-z0-9-]+\.md)\)", index))
    actual = {path.name for path in PREDICTIONS.glob("[0-9][0-9]-*.md")}

    assert linked == actual, (
        f"the index and the directory disagree. Only in the index: "
        f"{sorted(linked - actual)}. Only on disk: {sorted(actual - linked)}"
    )

    numbers = sorted(int(name[:2]) for name in actual)
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"the record numbering has a gap: {numbers}. A missing number is how a "
        "deleted record hides - the remaining files still agree with an index "
        "that was edited to match them."
    )


def test_the_cited_measurements_exist() -> None:
    """A scoring that cites data nobody can open is an assertion, not a record."""
    data = PREDICTIONS / "data"
    assert data.is_dir(), "the raw measurements directory is gone"

    index = read_data(data / "README.md")
    cited = set(re.findall(r"`([a-z0-9-]+\.json)`", index))
    present = {path.name for path in data.glob("*.json")}
    assert cited <= present, f"cited but missing: {sorted(cited - present)}"
    assert present, "no measurements are committed at all"
