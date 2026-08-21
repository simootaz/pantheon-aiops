"""The pushgateway job name exists in exactly one place.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from simulator.metrics_generator import PUSHGATEWAY_JOB
from tests.mechanism import read_mechanism, read_verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where the constant is allowed to appear, and where the rule itself is stated.
ALLOWED = {
    # The two constants themselves.
    "simulator/metrics_generator.py": "declares PUSHGATEWAY_JOB",
    "simulator/log_generator.py": "declares LOKI_JOB_LABEL",
    "tests/unit/test_no_job_name_literals.py": "states the rule",
    # A different concept that happens to share the spelling: the console
    # script's name, and docstrings showing how to invoke it.
    "simulator/cli.py": "the CLI command name, not a job identity",
    "simulator/scenario.py": "a docstring naming the CLI command",
    # The push path's spelling is asserted here deliberately - see the test below.
    "tests/unit/test_simulator_components.py": "asserts the push path's URL",
}

#: Both spellings. The wrong one is what every reset used for a week, so a guard
#: that only forbids the right one would have passed throughout the defect.
SPELLINGS = (PUSHGATEWAY_JOB, PUSHGATEWAY_JOB.replace("-", "_"))


def _tracked() -> list[Path]:
    return [
        path
        for pattern in ("*.py", "*.yml", "*.yaml", "*.sh")
        for path in REPO_ROOT.rglob(pattern)
        if not any(part in {".venv", "node_modules", "__pycache__", ".git"} for part in path.parts)
    ]


def test_the_job_name_is_never_written_out_again() -> None:
    """Correcting the three known callers leaves the fourth to be written next week.

    `metrics_generator` pushed to `pantheon-sim` while every reset deleted
    `pantheon_sim`, and the pushgateway answers 202 for a group that does not
    exist - so the mismatch was invisible in every gate and harness for a week.

    The fix is one exported constant, and this is what keeps it one.
    """
    offenders: list[str] = []
    for path in _tracked():
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in ALLOWED:
            continue
        # Verbatim, because line numbers are the point: `read_mechanism` strips
        # comments, so offsets computed against it do not correspond to the
        # file, and the first version of this guard reported locations that did
        # not exist. A comment mentioning the job name is also worth flagging.
        body = read_verbatim(path, why="line numbers must match the file, and comments count too")
        for spelling in SPELLINGS:
            for match in re.finditer(rf'["\'/]{re.escape(spelling)}\b', body):
                line = body[: match.start()].count("\n") + 1
                offenders.append(f"{relative}:{line} spells out {spelling!r}")

    assert not offenders, (
        "the pushgateway job name is written out instead of imported:\n  "
        + "\n  ".join(offenders)
        + "\n\nImport PUSHGATEWAY_JOB, or call MetricsGenerator().reset()."
    )


def test_both_directions_of_the_job_name_are_asserted() -> None:
    """A constant used in two directions needs asserting in both.

    `test_simulator_components.py` asserted the PUSH path spelled it
    `pantheon-sim`. The DELETE path had no test at all, so the half that was
    wrong was the half nobody checked - the same shape as a guard that catches
    component removals but not additions.
    """
    components = read_mechanism(REPO_ROOT / "tests" / "unit" / "test_simulator_components.py")
    assert "/metrics/job/pantheon-sim" in components, (
        "nothing asserts the push path's job name any more"
    )

    # Walked, not grepped. The first version asserted the substring
    # "PushgatewayNotClearedError" appeared in the module - which the class
    # DEFINITION satisfies, so deleting the raise from reset() left the guard
    # green. A substring that appears in two places tests neither.
    tree = ast.parse(read_mechanism(REPO_ROOT / "simulator" / "metrics_generator.py"))
    reset = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "reset"
        ),
        None,
    )
    assert reset is not None, "the delete path has no reset() to assert against"

    raised = {
        exc.func.id
        for node in ast.walk(reset)
        if isinstance(node, ast.Raise)
        and isinstance(exc := node.exc, ast.Call)
        and isinstance(exc.func, ast.Name)
    }
    assert "PushgatewayNotClearedError" in raised, (
        "reset() does not raise PushgatewayNotClearedError, so a 202 over a "
        f"missing group would again read as success. It raises: {sorted(raised) or 'nothing'}"
    )
