"""Guards that the public repository carries no assistant-tooling fingerprints.

The repository is public. Which local tools a contributor happens to use is
their business and must not be recorded in tracked files - not in filenames, not
in contents, not in comments or docs. See
docs/adr/0003-neutral-repository-documentation.md.

This is enforced rather than remembered, for the same reason the structural
guards exist: a convention nothing checks is a convention that rots.

Scope note: this checks *tracked* files only, via `git ls-files`. Untracked and
gitignored files are deliberately out of scope - local pointer files are
permitted precisely because they never enter the repository. Commit messages are
not checked here; see the ADR.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Substrings that must not appear in any tracked file's path or contents,
# matched case-insensitively.
FORBIDDEN = (
    "claude",
    "anthropic",
    "ai-generated",
    "co-authored-by",
    "\N{ROBOT FACE}",
)

# This scanner necessarily spells the forbidden terms out, so it excludes
# itself. Every other tracked file - including the sibling structural guards -
# is scanned.
SELF = Path(__file__).resolve()

# Lockfiles and generated artifacts are scanned too: a dependency named after a
# vendor would be a real finding, not a false positive.


def _tracked_files() -> list[Path]:
    """Every file git tracks, as absolute paths."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return [REPO_ROOT / name for name in result.stdout.split("\0") if name and name.strip()]


def test_no_tooling_fingerprints_in_tracked_paths() -> None:
    """No tracked file is named after an assistant tool."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _tracked_files()
        if any(term in str(path).lower() for term in FORBIDDEN)
    ]
    assert not offenders, f"tracked paths carrying tooling fingerprints: {offenders}"


def test_no_tooling_fingerprints_in_tracked_contents() -> None:
    """No tracked file mentions an assistant tool."""
    offenders: list[str] = []

    for path in _tracked_files():
        if path.resolve() == SELF or not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        hits = sorted({term for term in FORBIDDEN if term in text})
        if hits:
            offenders.append(f"{path.relative_to(REPO_ROOT)} -> {hits}")

    assert not offenders, "tracked files carrying tooling fingerprints:\n  " + "\n  ".join(
        offenders
    )


def test_repository_map_is_tracked_and_canonical() -> None:
    """docs/REPOSITORY_MAP.md is the committed map, and it is substantial.

    A neutralisation that quietly dropped the map instead of moving it would
    pass the two tests above while destroying the thing they protect.
    """
    tracked = {path.relative_to(REPO_ROOT).as_posix() for path in _tracked_files()}
    assert "docs/REPOSITORY_MAP.md" in tracked

    body = (REPO_ROOT / "docs" / "REPOSITORY_MAP.md").read_text(encoding="utf-8")
    for heading in (
        "## Project identity",
        "## Language boundaries",
        "## Folder map",
        "## Where do I put X?",
        "## Generated files",
        "## Standing decisions",
        "## Git Flow rules",
        "## Commands",
        "## Phase roadmap",
        "## Structure changelog",
    ):
        assert heading in body, f"repository map is missing section: {heading}"
