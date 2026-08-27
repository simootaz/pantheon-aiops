"""An exemption from the coverage floor must name a gate, and the gate must exist.

Every entry in `EXEMPT` is a module CI stops protecting. That is sometimes the
honest answer - `core/store/postgres.py` cannot execute a line without a
database, and CI's Python job starts none - but it is never a free one, so the
claim has to be checkable.

Two things are checked, because an exemption can be wrong in two ways. It can
name no gate, which makes it an assertion that someone tested this somehow. Or
it can name a gate that does not exist, which reads exactly like a real one and
is worse - the reader sees a target name and stops asking.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.coverage_floor import EXEMPT, FLOOR
from tests.mechanism import read_data

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_targets() -> set[str]:
    """Every target the Makefile actually defines."""
    makefile = read_data(REPO_ROOT / "Makefile")
    return set(re.findall(r"^([a-zA-Z][\w-]*):", makefile, re.MULTILINE))


def test_every_exemption_names_a_gate_that_exists() -> None:
    """A named gate nobody wrote is worse than no gate named at all.

    It reads as evidence. A reviewer sees `gate="test-flow-one"`, recognises the
    shape of a make target, and stops asking whether it runs the module.
    """
    targets = _make_targets()
    assert targets, "no make targets were parsed; the check would pass vacuously"

    for module, exemption in sorted(EXEMPT.items()):
        assert exemption.gate, f"{module} is exempt and names no gate"
        assert exemption.gate in targets, (
            f"{module} is exempt on the strength of `make {exemption.gate}`, which the "
            f"Makefile does not define. Targets: {sorted(targets)}"
        )


def test_every_exemption_states_what_its_gate_covers() -> None:
    """ "Needs a database" describes the module. It does not describe coverage.

    The reason has to say what the gate executes, so the next reader can check
    the claim against the module instead of taking it.
    """
    for module, exemption in sorted(EXEMPT.items()):
        assert len(exemption.reason.split()) >= 12, (
            f"{module}: the reason is too short to say what `make {exemption.gate}` "
            f"actually covers - {exemption.reason!r}"
        )


def test_every_exempt_module_exists() -> None:
    """An exemption outliving its module silently protects nothing.

    Rename the file and the entry keeps matching nothing forever, which looks
    identical to an exemption that is doing its job.
    """
    for module in sorted(EXEMPT):
        assert (REPO_ROOT / module).is_file(), (
            f"{module} is exempt from the coverage floor and does not exist. Remove the "
            "entry, or fix the path - a stale exemption is indistinguishable from a live one."
        )


def test_the_exemption_list_is_small_and_deliberate() -> None:
    """A floor with many exemptions is a floor that has stopped being one.

    Not a hard cap on principle - it is a tripwire. Crossing it should force
    someone to ask whether the modules are really untestable or whether the
    floor has become inconvenient.
    """
    assert len(EXEMPT) <= 3, (
        f"{len(EXEMPT)} modules are exempt from the {FLOOR}% floor. Each one is a module "
        "CI does not protect; at this many, the floor is protecting less than it appears to."
    )
