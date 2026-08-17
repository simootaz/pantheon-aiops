"""Per-module coverage floor for modules that contain decision points.

Not a test module - pytest does not collect it. `make test` runs it after
pytest, against the JSON report pytest-cov writes.

WHY THIS EXISTS
---------------
An aggregate coverage floor over a declaration-heavy codebase measures almost
nothing. Pantheon is 61% Pydantic field declarations, every one of which counts
as covered merely by being imported. The overall figure therefore sits near
99% no matter how much untested logic is added, because untested logic is a
rounding error against hundreds of free statements.

coverage.py supports only a global `fail_under`, so the per-module floor is
applied here. Modules with **zero branches** are exempt: they are declarations,
and a floor over them would measure import success, which is already covered by
the tests that import them.

The number is set from what the code actually reports, not from an aspiration.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "coverage.json"

#: Floor for any module containing at least one branch point. Set from the
#: measured baseline with a little headroom, so it bites on new untested logic
#: rather than on ordinary churn.
FLOOR = 90.0


def main() -> int:
    if not REPORT.is_file():
        print(f"coverage-floor: {REPORT.name} not found; run pytest first", file=sys.stderr)
        return 1

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    branching = {
        name: summary
        for name, entry in data["files"].items()
        if (summary := entry["summary"])["num_branches"] > 0
    }

    if not branching:
        print("coverage-floor: no modules with branches; nothing to enforce", file=sys.stderr)
        return 1

    failures = [
        (name, summary["percent_covered"])
        for name, summary in sorted(branching.items())
        if summary["percent_covered"] < FLOOR
    ]

    worst = min(summary["percent_covered"] for summary in branching.values())
    print(
        f"coverage-floor: {len(branching)} modules with decision points, "
        f"lowest {worst:.1f}%, floor {FLOOR:.0f}%"
    )

    for name, percent in failures:
        print(f"  {percent:5.1f}%  {name}", file=sys.stderr)

    if failures:
        print(
            f"coverage-floor: {len(failures)} module(s) below the floor. The aggregate "
            "figure hides this, which is why the floor is per-module.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
