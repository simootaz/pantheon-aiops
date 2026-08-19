"""Guards over the things that made fifteen CI runs fail while local runs passed.

Every failure below was invisible locally, and each for its own reason. That is
the pattern worth guarding: a local pass is evidence about a laptop, and these
assert the properties CI depends on that a laptop does not.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.mechanism import read_data, read_mechanism

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MAKEFILE = REPO_ROOT / "Makefile"

#: Go toolchain the runners install. Not the language version in `go.work`:
#: that says what the modules are written against, this says what is installed.
#: The pinned generators require it - go-jsonschema v0.24.1 and golangci-lint
#: v2.12.2 both need >= 1.25.0.
REQUIRED_GO_MAJOR_MINOR = (1, 25)


def workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def go_versions() -> dict[str, str]:
    """`GO_VERSION` as declared by each workflow that declares one."""
    found: dict[str, str] = {}
    for path in workflows():
        match = re.search(r'^\s*GO_VERSION:\s*"([^"]+)"', read_mechanism(path), re.MULTILINE)
        if match:
            found[path.name] = match.group(1)
    return found


# --- the Go toolchain that broke two jobs ------------------------------------


def test_every_workflow_installs_a_go_new_enough_for_the_pinned_tools() -> None:
    """The failure that hid behind a one-line message on every local run.

    A developer machine on Go 1.23 downloads 1.25 to satisfy these tools and
    prints `switching to go1.25.13`. CI sets GOTOOLCHAIN=local, which forbids
    that, so it fails where the laptop silently succeeded. Fifteen runs.
    """
    declared = go_versions()
    assert declared, "no workflow declares GO_VERSION any more"

    for name, version in declared.items():
        parts = tuple(int(piece) for piece in version.split(".")[:2])
        assert parts >= REQUIRED_GO_MAJOR_MINOR, (
            f"{name} installs Go {version}, but the pinned generators need "
            f"{'.'.join(map(str, REQUIRED_GO_MAJOR_MINOR))}+. With GOTOOLCHAIN=local "
            "the runner cannot switch, so the job fails."
        )


def test_the_workflows_agree_on_one_go_version() -> None:
    """Two workflows drifting apart is the same bug arriving twice."""
    declared = go_versions()
    assert len(set(declared.values())) == 1, f"workflows disagree on GO_VERSION: {declared}"


def test_gotoolchain_stays_local_in_ci() -> None:
    """The auto-switch is the thing that hid the mismatch; keep it off in CI.

    Without `GOTOOLCHAIN=local` a runner would quietly download whatever the
    tools ask for, and the version actually used stops being the version anyone
    pinned - which is exactly the state that produced fifteen red runs while
    every local run looked fine.
    """
    using_go = [path.name for path in workflows() if "GO_VERSION" in read_mechanism(path)]
    assert using_go, "no workflow sets up Go"
    for name in using_go:
        body = read_mechanism(WORKFLOWS / name)
        assert "GOTOOLCHAIN: local" in body, (
            f"{name} sets up Go without GOTOOLCHAIN=local, so it would silently "
            "use a toolchain nobody pinned"
        )


# --- the pnpm setup that broke the dashboard job -----------------------------


def test_the_pnpm_action_is_pointed_at_the_dashboard_package_json() -> None:
    """`action-setup` reads the ROOT package.json by default, and there is none.

    Every run failed with "No pnpm version is specified" while a comment beside
    the step claimed dashboard/package.json was being read. The comment was the
    intent; `package_json_file` is the mechanism.
    """
    body = read_data(WORKFLOWS / "ci-dashboard.yml")
    assert "pnpm/action-setup" in body, "the dashboard workflow no longer sets up pnpm"
    assert "package_json_file: dashboard/package.json" in body, (
        "pnpm/action-setup has no package_json_file, so it looks for a root "
        "package.json this repo does not have"
    )
    assert not (REPO_ROOT / "package.json").exists(), (
        "a root package.json now exists - if that is deliberate, this guard's "
        "reasoning needs revisiting rather than deleting"
    )


def test_the_dashboard_declares_the_pnpm_it_wants() -> None:
    """The version CI installs comes from here, so it has to be here."""
    import json

    package = json.loads(read_data(REPO_ROOT / "dashboard" / "package.json"))
    assert package.get("packageManager", "").startswith("pnpm@"), (
        "dashboard/package.json declares no packageManager, so CI has no version to install"
    )


def test_pnpm_settings_live_where_pnpm_reads_them() -> None:
    """Since pnpm 10 a `pnpm` key in package.json is IGNORED, silently.

    Overrides were first added there and changed nothing - pnpm warned and the
    warning scrolled past. A fix that looks applied and does nothing is worse
    than no fix.
    """
    import json

    package = json.loads(read_data(REPO_ROOT / "dashboard" / "package.json"))
    assert "pnpm" not in package, (
        "dashboard/package.json has a `pnpm` key. pnpm 10+ ignores it; settings "
        "belong in pnpm-workspace.yaml"
    )

    workspace = REPO_ROOT / "dashboard" / "pnpm-workspace.yaml"
    assert workspace.is_file(), "dashboard/pnpm-workspace.yaml is missing"
    settings = yaml.safe_load(read_data(workspace)) or {}
    assert settings.get("overrides"), (
        "no overrides in pnpm-workspace.yaml. sharp and postcss carry HIGH "
        "advisories transitively through next, and trivy fs fails CI on them."
    )


# --- the make target that swept in gates CI cannot serve ---------------------


def test_each_integration_gate_has_its_own_target() -> None:
    """`make test-sim` ran the whole directory, so new gates joined it silently.

    CI's simulator job starts prometheus, loki and pushgateway - not the API,
    not alertmanager. When the connector and alert gates landed in the same
    directory they were swept in and errored, while the simulator assertions
    they were reported alongside had all passed.
    """
    body = read_mechanism(MAKEFILE)
    sweeping = re.findall(r"pytest tests/integration\s+-m", body)
    assert not sweeping, (
        "a target runs `pytest tests/integration` wholesale. Each gate needs "
        "different services up, so each names its own file."
    )

    gates = sorted(path.name for path in (REPO_ROOT / "tests" / "integration").glob("test_*.py"))
    for gate in gates:
        assert gate in body, (
            f"{gate} is not named by any Makefile target, so nothing runs it. "
            "Add a target, or the gate exists and never executes."
        )
