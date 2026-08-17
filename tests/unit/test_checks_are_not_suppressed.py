"""A check whose output is suppressed is not a check.

This is a distinct failure from a guard that cannot fail. Here the rule exists,
is selected, and fires correctly — and the result is discarded before anyone
sees it. The tool did its job; the harness threw the answer away.

It is how `assert ... or True` reached a commit in a repository whose central
rule is *if you have not seen it red, you have not tested it*. Ruff's `SIM222`
flagged it. The loop ran `ruff check --fix -q … >/dev/null 2>&1`, so nobody
found out.

WHAT IS AND IS NOT SUPPRESSION
------------------------------
Discarding *chatter* is fine when the exit code is still enforced — `verify.sh`
sends generator stdout to /dev/null under `set -e`, and prints every diff to
stderr on failure. Discarding the *verdict* is not.

So these guards check the two places a verdict can be silently dropped:

1. a Makefile target that runs a check and ignores its result;
2. a workflow step marked `continue-on-error` with nothing downstream that
   reads its outcome.

`security.yml` uses `continue-on-error` deliberately, so findings upload before
the job fails. That is correct, and the second guard confirms it rather than
flagging it.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAKEFILE = REPO_ROOT / "Makefile"

#: Targets whose whole purpose is to report a verdict.
CHECK_TARGETS = (
    "lint",
    "typecheck",
    "test",
    "lint-go",
    "test-go",
    "lint-ts",
    "test-ts",
    "codegen-verify",
)

#: Constructs that drop a verdict rather than merely quieting output.
VERDICT_DROPPING = ("|| true", "|| :", "; true", "exit 0")


def _make_recipes() -> dict[str, list[str]]:
    """Target name -> its recipe lines."""
    recipes: dict[str, list[str]] = {}
    current: str | None = None

    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("\t") and current:
            recipes[current].append(line)
            continue
        match = re.match(r"^([a-zA-Z0-9_-]+):(?!=)", line)
        if match:
            current = match.group(1)
            recipes.setdefault(current, [])
        elif not line.startswith("\t"):
            current = None
    return recipes


def test_no_check_target_drops_its_verdict() -> None:
    """A check target must let a failure become a failure."""
    recipes = _make_recipes()
    offenders: list[str] = []

    for target in CHECK_TARGETS:
        assert target in recipes, f"Makefile has no target {target!r}"
        for line in recipes[target]:
            for construct in VERDICT_DROPPING:
                if construct in line:
                    offenders.append(f"{target}: {line.strip()}  [{construct}]")

    assert not offenders, "check targets that swallow their result:\n  " + "\n  ".join(offenders)


def test_no_check_target_hides_its_output_entirely() -> None:
    """Redirecting a checker's stdout *and* stderr leaves nothing to read.

    `clean` is exempt: it is a command, not a check, and `find`'s complaint
    about a directory that vanished mid-traversal is noise.
    """
    recipes = _make_recipes()
    offenders = [
        f"{target}: {line.strip()}"
        for target in CHECK_TARGETS
        for line in recipes[target]
        if ">/dev/null" in line and "2>&1" in line
    ]
    assert not offenders, "check targets with all output discarded:\n  " + "\n  ".join(offenders)


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job.get("steps", []) if isinstance(step, dict)]


def test_continue_on_error_is_always_paired_with_an_outcome_check() -> None:
    """`continue-on-error` without a downstream check is a green failure.

    Used correctly it means "record this result, act on it later" - which is why
    security.yml uses it, so SARIF uploads before the job fails. Used without the
    later action it means "ignore this result", and the step becomes decorative.
    """
    offenders: list[str] = []

    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in workflow.get("jobs", {}).items():
            if not isinstance(job, dict):
                continue
            steps = _steps(job)
            lenient = [s for s in steps if s.get("continue-on-error") is True]
            if not lenient:
                continue

            body = yaml.safe_dump(steps)
            for step in lenient:
                step_id = step.get("id")
                if not step_id:
                    offenders.append(
                        f"{path.name}:{job_name} - a continue-on-error step has no id, "
                        "so nothing can read its outcome"
                    )
                    continue
                if f"steps.{step_id}.outcome" not in body:
                    offenders.append(
                        f"{path.name}:{job_name}:{step_id} - continue-on-error with no "
                        "downstream check of steps.{id}.outcome"
                    )

    assert not offenders, "steps whose failure would go unnoticed:\n  " + "\n  ".join(offenders)


def test_security_scans_use_continue_on_error_correctly() -> None:
    """The deliberate case, confirmed rather than merely tolerated.

    Every scan must be lenient *and* have a step that fails the job on its
    outcome - otherwise findings would upload and the build would stay green.
    """
    workflow = yaml.safe_load((WORKFLOWS / "security.yml").read_text(encoding="utf-8"))

    scanning_jobs = [
        (name, job)
        for name, job in workflow["jobs"].items()
        if any(step.get("continue-on-error") for step in _steps(job))
    ]
    assert len(scanning_jobs) >= 4, (
        f"expected at least four lenient scan jobs, found {len(scanning_jobs)}"
    )

    for name, job in scanning_jobs:
        rendered = yaml.safe_dump(_steps(job))
        assert "steps.scan.outcome == 'failure'" in rendered, (
            f"security.yml:{name} scans leniently but never fails on the outcome"
        )


def test_verify_sh_prints_the_diff_it_captured() -> None:
    """Capturing a diff to a file is fine only if failure prints it.

    Otherwise the drift is detected, the build fails, and the developer is told
    nothing about what drifted.
    """
    source = (REPO_ROOT / "codegen" / "verify.sh").read_text(encoding="utf-8")

    assert re.search(r"^set -euo pipefail$", source, re.MULTILINE), (
        "verify.sh does not set -e, so a failing generator would not fail the script"
    )

    captured = len(re.findall(r'>"\$TMP/[a-z]+\.diff"', source))
    printed = len(re.findall(r'head -\d+ "\$TMP/[a-z]+\.diff" >&2', source))
    assert captured == printed > 0, (
        f"verify.sh captures {captured} diffs but prints {printed}; a captured diff "
        "nobody prints is drift detected and not reported"
    )
