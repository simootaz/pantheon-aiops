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
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "coverage.json"

#: Floor for any module containing at least one branch point. Set from the
#: measured baseline with a little headroom, so it bites on new untested logic
#: rather than on ordinary churn.
FLOOR = 90.0


class Exemption(NamedTuple):
    """A module the floor does not apply to, and the gate that does apply.

    Both fields are load-bearing. `gate` is a make target that must exist -
    `tests/unit/test_coverage_exemptions.py` fails the build if it does not -
    so an exemption cannot name a gate nobody wrote. `reason` has to say what
    that gate actually executes, because "needs a database" is a description of
    the module and not a claim anyone can check.
    """

    gate: str
    reason: str


#: Modules the per-module floor does not apply to.
#:
#: **An entry here is a module CI stops protecting.** Adding one is a deliberate
#: act with a cost, which is why it needs a gate that exists and a reason that
#: says what the gate covers.
#:
#: Draw the boundary where the claim becomes true, not where the module ends. The
#: store was split for exactly this: `core/store/investigations.py` holds the
#: Protocol, the in-memory implementation and `dsn()` - all pure logic, all under
#: the floor - and only the driver code moved to the exempt module. A
#: whole-module exemption would have covered `dsn()`, which touches no database
#: and had already been wrong once.
EXEMPT: dict[str, Exemption] = {
    "core/store/postgres.py": Exemption(
        gate="test-flow-one",
        reason=(
            "every path needs a live Postgres and every path is executed by the "
            "flow-one gate: the pool being created, the table being made, save, "
            "get, recent and close. CI's Python job starts no database, so none "
            "of it is covered there."
        ),
    ),
    "core/store/postgres_providers.py": Exemption(
        gate="test-providers",
        reason=(
            "every path needs a live Postgres and every path is executed by the "
            "provider gate: schema creation, create, get, list, update, delete "
            "and reveal_key. That gate also reads the sealed_key column on a "
            "second connection and asserts the plaintext is absent, which is the "
            "one claim no unit test can make. The store was split for this: the "
            "Protocol, the sealing in-memory implementation, row_to_stored and "
            "config_from_input stayed in core/store/providers.py and remain "
            "under the floor, because that is where a mistake leaks a key."
        ),
    ),
}


def _relative(name: str) -> str:
    """Coverage reports OS-native paths; the exemption list is written one way."""
    return name.replace("\\", "/")


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
        if summary["percent_covered"] < FLOOR and _relative(name) not in EXEMPT
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
