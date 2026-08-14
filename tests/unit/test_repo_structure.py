"""Structural guards for the repository scaffold.

Phase 0 delivers a structure, so the structure is what Phase 0 tests. These
guards fail loudly if a future change breaks an invariant that CLAUDE.md
promises: the agent roster, package initialisers, phase markers on every module,
and the do-not-edit banner on generated directories.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The ten domain agents. Zeus is the orchestrator and lives in core/, not here.
# Keep in sync with the agent table in CLAUDE.md.
AGENT_DOMAINS = frozenset(
    {
        "anomaly",
        "capacity",
        "chaos",
        "ci_triage",
        "dora",
        "knowledge",
        "log_clustering",
        "manifest_review",
        "nl_query",
        "reporting",
    }
)

# Directories holding only machine-generated output.
GENERATED_DIRS = (
    "core/contracts/export",
    "connectors/kubernetes/pkg/contracts",
    "dashboard/types/generated",
)

# Trees that are not Python and must not be walked looking for packages.
NON_PYTHON_TREES = frozenset({".git", ".venv", "dashboard", "deploy", "docs", "pkg", "cmd"})


def _python_files() -> list[Path]:
    """Every first-party Python file, excluding non-Python trees."""
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*.py"))
        if not any(part in NON_PYTHON_TREES for part in path.relative_to(REPO_ROOT).parts)
    ]


def test_agent_roster_matches_claude_md() -> None:
    """agents/ holds exactly the ten domain agents, plus _base."""
    found = {
        entry.name
        for entry in (REPO_ROOT / "agents").iterdir()
        if entry.is_dir() and not entry.name.startswith((".", "__"))
    }
    assert found - {"_base"} == set(AGENT_DOMAINS)


def test_every_agent_package_is_complete() -> None:
    """Each agent ships agent.py, manifest.yaml, tools.py, prompts/ and tests/."""
    for domain in sorted(AGENT_DOMAINS):
        base = REPO_ROOT / "agents" / domain
        for required in ("__init__.py", "agent.py", "manifest.yaml", "tools.py"):
            assert (base / required).is_file(), f"agents/{domain}/{required} is missing"
        for required_dir in ("prompts", "tests"):
            assert (base / required_dir).is_dir(), f"agents/{domain}/{required_dir}/ is missing"


def test_every_python_package_has_an_init() -> None:
    """Any directory holding a Python module is an importable package."""
    missing = sorted(
        str(path.parent.relative_to(REPO_ROOT))
        for path in _python_files()
        if not (path.parent / "__init__.py").exists()
    )
    assert not missing, f"directories with .py but no __init__.py: {missing}"


def test_every_python_module_declares_its_phase() -> None:
    """Every module carries a docstring and a phase marker, per the scaffold rule."""
    undocumented: list[str] = []
    unmarked: list[str] = []

    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(REPO_ROOT))
        if ast.get_docstring(ast.parse(source)) is None:
            undocumented.append(relative)
        if "Phase:" not in source:
            unmarked.append(relative)

    assert not undocumented, f"modules without a docstring: {undocumented}"
    assert not unmarked, f"modules without a Phase marker: {unmarked}"


def test_generated_directories_warn_against_hand_editing() -> None:
    """Generated output directories carry a do-not-edit README."""
    for relative in GENERATED_DIRS:
        readme = REPO_ROOT / relative / "README.md"
        assert readme.is_file(), f"{relative}/README.md is missing"
        assert "do not edit" in readme.read_text(encoding="utf-8").lower()
