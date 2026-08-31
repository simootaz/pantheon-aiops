"""An exemption from the coverage floor must name a gate, and the gate must exist.

Every entry in `EXEMPT` is a module CI stops protecting. That is sometimes the
honest answer - `core/store/postgres.py` cannot execute a line without a
database, and CI's Python job starts none - but it is never a free one, so the
claim has to be checkable.

An exemption can be wrong in three ways, and the third is the one this file
originally missed. It can name no gate, which makes it an assertion that someone
tested this somehow. It can name a gate that does not exist, which reads exactly
like a real one and is worse - the reader sees a target name and stops asking.

Or it can name a gate that exists and does not run the module. That stayed
possible for as long as this file checked only the name against the Makefile:
`gate="test-flow-one"` on the provider store would have satisfied every check
below while nothing executed a line of it. The guard verified the label rather
than the thing the label refers to - see docs/guard-verification.md.

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


def _recipe(target: str) -> str:
    """The commands a make target actually runs, continuations included."""
    makefile = read_data(REPO_ROOT / "Makefile")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", makefile, re.MULTILINE)
    return match.group(1) if match else ""


def _modules_imported_by(path: Path) -> set[str]:
    """Dotted module names a test file imports, as written."""
    return set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", read_data(path), re.MULTILINE))


def test_every_exemption_names_a_gate_that_runs_the_module() -> None:
    """The check this file was missing, and the one the others imply.

    A gate that exists is not a gate that covers. Nothing stopped an exemption
    from naming `test-flow-one` - a real target, green on every run - for a
    module that target never imports. Every other check here would have passed,
    and the module would have been unprotected in both directions at once: below
    the floor by exemption, and outside the gate by fact.

    So the gate's recipe is read, the test files it runs are read, and the exempt
    module has to be imported by name. A direct import rather than a transitive
    walk, deliberately: the gate that claims to cover a module should say so.
    """
    for module, exemption in sorted(EXEMPT.items()):
        recipe = _recipe(exemption.gate)
        assert recipe, (
            f"`make {exemption.gate}` is defined but has no recipe, so it runs "
            f"nothing and cannot cover {module}"
        )

        runs = [REPO_ROOT / rel for rel in re.findall(r"tests/[\w/]+\.py", recipe)]
        assert runs, (
            f"`make {exemption.gate}` names no test file, so there is nothing to "
            f"check {module} against. Recipe: {recipe.strip()!r}"
        )

        dotted = module.removesuffix(".py").replace("/", ".")
        importers = [path.name for path in runs if dotted in _modules_imported_by(path)]
        assert importers, (
            f"{module} is exempt on the strength of `make {exemption.gate}`, and "
            f"none of {[path.name for path in runs]} imports {dotted}. The gate "
            "exists, is green, and does not run the module."
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
