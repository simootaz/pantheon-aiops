"""The Makefile recipes that needed a shell, written so they need none.

WHY THIS EXISTS
-----------------
Three targets used POSIX coreutils directly - `[`, `cp`, `rm`, `find`, and a
`grep | sed | awk` pipeline. On Windows make runs recipes through cmd.exe, which
has none of them, so `make up`, `make clean` and `make help` all failed with

    '[' is not recognized as an internal or external command

They joined every live gate, which failed the same way for a different reason
(`VAR=value command`). The pattern is one thing: the Makefile had been written
as though a POSIX shell were always underneath it, and CI runs Linux, so nothing
noticed until somebody ran the targets on the machine they were written for.

WHY PYTHON RATHER THAN A PORTABLE SHELL INCANTATION
-----------------------------------------------------
`uv` and Python are already required to do anything in this repository - every
other recipe runs `uv run`. So Python is the one interpreter guaranteed present,
which is more than can be said for `sh` on Windows or `awk` anywhere.

And it is testable. `make help`'s awk pipeline had never been exercised by
anything; these functions are, by `tests/unit/test_make_tasks.py`.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: `## target: description` - the only lines `make help` renders.
HELP_LINE = re.compile(r"^## ([^:]+):(.*)$")

#: Cache and build directories `make clean` removes. Named rather than globbed
#: from a pattern, because a glob that matched one directory too many would
#: delete work, and this runs unattended in nobody's presence.
CLEANABLE = (
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "htmlcov",
    "coverage.xml",
    "coverage.json",
    ".coverage",
    "dist",
    "build",
    "bin",
    "dashboard/.next",
    "dashboard/.turbo",
)

#: Directories removed wherever they appear. `__pycache__` only: a recursive
#: delete driven by a wider list is one typo away from being a recursive delete
#: of something else.
CLEANABLE_TREES = ("__pycache__",)


def render_help(makefile: str) -> str:
    """The target table `make help` prints.

    Replaces `grep -E '^## ' | sed | awk`. Same output, and the alignment is a
    format string rather than an awk `printf` nobody could run to check.
    """
    rows: list[str] = []
    for line in makefile.splitlines():
        match = HELP_LINE.match(line)
        if match:
            name, description = match.group(1).strip(), match.group(2).strip()
            rows.append(f"  \033[36m{name:<16}\033[0m {description}")
    return "\n".join(rows)


def ensure_env(target: Path, template: Path) -> bool:
    """Copy `template` to `target` when there is no `target`. Returns whether it did.

    Replaces `[ -f .env ] || cp .env.example .env`.

    Never overwrites. The file it would clobber is the one holding somebody's
    local passwords, and `make up` is a command people run without thinking
    about it.
    """
    if target.exists():
        return False
    if not template.exists():
        raise FileNotFoundError(f"{template} is missing, so {target} cannot be created from it")
    shutil.copyfile(template, target)
    return True


def clean(root: Path) -> list[str]:
    """Remove build and cache artefacts. Returns what was removed.

    Replaces four `rm -rf` lines and a `find -exec rm`.

    Everything is resolved and checked to be inside `root` before it is touched.
    A path that escaped - through a symlink, or a name with `..` in it - would
    make this a recursive delete somewhere nobody was looking, and the shell
    version had no such check because writing one in `find` is impractical.
    """
    removed: list[str] = []

    for name in CLEANABLE:
        removed.extend(_remove(root / name, root))

    for tree in CLEANABLE_TREES:
        for found in sorted(root.rglob(tree)):
            removed.extend(_remove(found, root))

    return removed


def _remove(path: Path, root: Path) -> list[str]:
    """Delete one path, refusing anything outside `root`."""
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        # Outside the repository, or unresolvable. Skipped rather than raised:
        # `make clean` failing on one odd symlink would leave the rest of the
        # tree dirty, and the point of the check is to not delete it.
        return []

    if not resolved.exists():
        return []
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
    else:
        resolved.unlink(missing_ok=True)
    return [str(path.relative_to(root)) if path.is_relative_to(root) else str(path)]


def main(argv: list[str]) -> int:
    """One subcommand per recipe that needed a shell."""
    command = argv[1] if len(argv) > 1 else ""

    if command == "help":
        print(render_help((REPO_ROOT / "Makefile").read_text(encoding="utf-8")))
        return 0

    if command == "ensure-env":
        created = ensure_env(
            REPO_ROOT / "deploy" / "compose" / ".env",
            REPO_ROOT / "deploy" / "compose" / ".env.example",
        )
        if created:
            print("created deploy/compose/.env from .env.example")
        return 0

    if command == "clean":
        for entry in clean(REPO_ROOT):
            print(f"removed {entry}")
        return 0

    print(f"unknown task {command!r}; expected one of: help, ensure-env, clean", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
