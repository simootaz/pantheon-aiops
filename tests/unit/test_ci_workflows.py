"""Guards for the CI workflows.

actionlint and zizmor check workflow syntax and security. These guard the
properties specific to this repository: that every action is pinned to a commit
SHA, that the aggregator really does require every check, and that the codegen
job's generator pins agree with the scripts it verifies.

The last one matters most. If the workflow and codegen/gen_*.sh disagree about a
generator version, CI regenerates with a different tool than a developer does
and reports drift that is not a contract change - which is exactly how a drift
detector gets ignored.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Reusable workflows the aggregator must call. Keep in sync with ci.yml.
REQUIRED_CHECKS = (
    "ci-python.yml",
    "ci-go.yml",
    "ci-dashboard.yml",
    "codegen-check.yml",
    "ci-deploy.yml",
    "security.yml",
)

# `uses:` values that are local paths rather than published actions.
_LOCAL = re.compile(r"^\./")
_SHA_PINNED = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def _load(path: Path) -> dict[Any, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} is not a mapping"
    return loaded


def _triggers(data: dict[Any, Any]) -> dict[str, Any]:
    """Return a workflow's `on:` block.

    YAML 1.1 resolves a bare `on` key to the boolean True, so PyYAML hands it
    back under True rather than "on". Both spellings are accepted here so the
    test does not depend on which quoting style a workflow uses.
    """
    raw = data.get("on", data.get(True))
    assert isinstance(raw, dict), "workflow has no usable `on:` block"
    return raw


def test_every_workflow_parses() -> None:
    """Every workflow is valid YAML and declares jobs."""
    files = _workflow_files()
    assert files, "no workflows found"
    for path in files:
        data = _load(path)
        assert "jobs" in data, f"{path.name} declares no jobs"


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    """Tags are mutable; a compromised tag is a supply-chain incident."""
    offenders: list[str] = []
    for path in _workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"^\s*(?:-\s*)?uses:\s*(\S+)", line)
            if not match:
                continue
            ref = match.group(1)
            if _LOCAL.match(ref) or _SHA_PINNED.match(ref):
                continue
            offenders.append(f"{path.name}:{number} -> {ref}")
    assert not offenders, "actions not pinned to a commit SHA:\n  " + "\n  ".join(offenders)


def test_aggregator_requires_every_check() -> None:
    """ci.yml is the single required status, so it must depend on all of them."""
    ci = _load(WORKFLOWS / "ci.yml")
    jobs = ci["jobs"]
    assert isinstance(jobs, dict)

    called = {
        str(job["uses"]).rsplit("/", 1)[-1]
        for job in jobs.values()
        if isinstance(job, dict) and "uses" in job
    }
    missing = set(REQUIRED_CHECKS) - called
    assert not missing, f"ci.yml does not call: {sorted(missing)}"

    gate = jobs["gate"]
    assert isinstance(gate, dict)
    needs = gate["needs"]
    assert isinstance(needs, list)

    calling_jobs = {name for name, job in jobs.items() if isinstance(job, dict) and "uses" in job}
    assert calling_jobs <= set(needs), f"gate does not require: {sorted(calling_jobs - set(needs))}"


def test_reusable_workflows_do_not_declare_their_own_triggers() -> None:
    """Only ci.yml owns triggers, otherwise every job runs twice per PR."""
    for name in REQUIRED_CHECKS:
        triggers = _triggers(_load(WORKFLOWS / name))
        assert set(triggers) == {"workflow_call"}, (
            f"{name} declares {sorted(triggers)}; reusable workflows must be workflow_call only"
        )


def test_codegen_workflow_pins_match_the_scripts() -> None:
    """The workflow and the generators must agree on tool versions."""
    workflow = (WORKFLOWS / "codegen-check.yml").read_text(encoding="utf-8")
    gen_go = (REPO_ROOT / "codegen" / "gen_go.sh").read_text(encoding="utf-8")
    gen_ts = (REPO_ROOT / "codegen" / "gen_ts.sh").read_text(encoding="utf-8")

    def one(pattern: str, haystack: str, what: str) -> str:
        found = re.search(pattern, haystack)
        assert found, f"could not read {what}"
        return found.group(1)

    assert one(r"EXPECTED_GO_JSONSCHEMA:\s*(\S+)", workflow, "workflow Go pin") == one(
        r'GO_JSONSCHEMA_VERSION="([^"]+)"', gen_go, "gen_go.sh pin"
    )
    assert one(r"EXPECTED_JSON_SCHEMA_TO_TS:\s*(\S+)", workflow, "workflow TS pin") == one(
        r'JSON_SCHEMA_TO_TS_VERSION="([^"]+)"', gen_ts, "gen_ts.sh pin"
    )


def test_workflows_declare_minimal_permissions_and_concurrency() -> None:
    """Default read-only, and never let two runs of a ref overlap."""
    for path in _workflow_files():
        data = _load(path)
        assert "permissions" in data, f"{path.name} does not scope permissions"
        assert "concurrency" in data, f"{path.name} declares no concurrency group"
        group = data["concurrency"]["group"]
        assert "github.ref" in str(group), f"{path.name} concurrency is not per-ref"


def test_go_workflow_avoids_the_impossible_build_command() -> None:
    """`go build ./...` cannot work from a non-module root - see the map.

    Comments are excluded on purpose: ci-go.yml explains at length *why* that
    command is absent, and the explanation is worth keeping. Only executable
    lines are checked.
    """
    body = (WORKFLOWS / "ci-go.yml").read_text(encoding="utf-8")
    executable = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "go build ./..." not in executable, (
        "ci-go.yml runs `go build ./...`, which is structurally invalid at the repo root"
    )
    assert "github.com/simootaz/pantheon-aiops/..." in executable


def test_dependabot_covers_every_go_module() -> None:
    """Dependabot does not walk go.work; each module needs its own entry."""
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    directories = {
        str(entry["directory"])
        for entry in config["updates"]
        if entry["package-ecosystem"] == "gomod"
    }
    expected = {
        "/pkg/mcpserver",
        "/pkg/contracts",
        "/connectors/kubernetes",
        "/cmd/pantheonctl",
        "/cmd/collector",
    }
    assert directories == expected, f"gomod entries drifted: {sorted(directories ^ expected)}"

    ecosystems = {str(entry["package-ecosystem"]) for entry in config["updates"]}
    assert {"pip", "gomod", "npm", "github-actions", "docker"} <= ecosystems
