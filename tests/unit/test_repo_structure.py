"""Structural guards for the repository scaffold.

Phase 0 delivers a structure, so the structure is what Phase 0 tests. These
guards fail loudly if a future change breaks an invariant that
docs/REPOSITORY_MAP.md promises: the agent roster, package initialisers, phase
markers on every module, and the do-not-edit banner on generated directories.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The ten domain agents. Zeus is the orchestrator and lives in core/, not here.
# Keep in sync with the agent table in docs/REPOSITORY_MAP.md.
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
    "pkg/contracts",
    "dashboard/types/generated",
)

# The three artifacts the codegen pipeline produces, all committed.
GENERATED_ARTIFACTS = (
    "core/contracts/export/pantheon.schema.json",
    "pkg/contracts/contracts.gen.go",
    "dashboard/types/generated/contracts.ts",
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


def test_agent_roster_matches_repository_map() -> None:
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


def test_generated_artifacts_are_committed() -> None:
    """The codegen pipeline's three outputs exist and are non-empty.

    verify.sh diffs against these committed copies, so a missing artifact would
    make the drift check vacuous rather than failing loudly.
    """
    for relative in GENERATED_ARTIFACTS:
        artifact = REPO_ROOT / relative
        assert artifact.is_file(), f"{relative} is missing - run 'make codegen'"
        assert artifact.stat().st_size > 0, f"{relative} is empty"


def test_generated_artifacts_declare_they_are_generated() -> None:
    """Each generated file says so in its own text, not just in a sibling README."""
    for relative in GENERATED_ARTIFACTS:
        head = (REPO_ROOT / relative).read_text(encoding="utf-8")[:400].lower()
        assert "generated" in head, f"{relative} does not announce that it is generated"
        assert "do not edit" in head or "not edit" in head, (
            f"{relative} does not warn against hand-editing"
        )


def test_every_exported_contract_model_is_closed() -> None:
    """Exported models forbid extra fields.

    This is not style. Pydantic only emits `additionalProperties: false` for
    closed models, and without it the TypeScript generator adds an
    `[k: string]: unknown` index signature to every interface - which silently
    reopens a contract that is meant to be closed.
    """
    from core.contracts import EXPORTED_MODELS

    assert EXPORTED_MODELS, "EXPORTED_MODELS is empty; codegen would emit nothing"
    open_models = [
        model.__name__ for model in EXPORTED_MODELS if model.model_config.get("extra") != "forbid"
    ]
    assert not open_models, f"models not extending ContractModel: {open_models}"


# ---------------------------------------------------------------------------
# Deploy skeleton and Delphi - added on feature/deploy-skeleton
# ---------------------------------------------------------------------------

# Images the Compose stack and CI expect to be able to build.
DOCKERFILES = (
    "api",
    "worker",
    "agent",
    "connector-py",
    "connector-go",
    "dashboard",
    "simulator",
)

# Delphi's modules, per docs/adr/0004-llm-provider-abstraction.md.
DELPHI_MODULES = (
    "gateway",
    "resolver",
    "fallback",
    "capability_matrix",
    "probe",
    "keyring",
    "catalog",
    "provider",
    "tracing",
)

DELPHI_ADAPTERS = ("chat_completions", "messages", "generate_content", "raw", "custom")


def test_every_dockerfile_exists() -> None:
    """One image per component, named as the Compose files reference them."""
    for name in DOCKERFILES:
        path = REPO_ROOT / "deploy" / "docker" / f"Dockerfile.{name}"
        assert path.is_file(), f"deploy/docker/Dockerfile.{name} is missing"


def test_object_storage_module_replaced_the_vendor_named_one() -> None:
    """ADR 0001: the Terraform module is provider-shaped, not vendor-shaped.

    Guards the rename specifically - a module named after one vendor invites
    vendor-specific resources back in.
    """
    assert (REPO_ROOT / "deploy/terraform/modules/object-storage").is_dir()
    assert not (REPO_ROOT / "deploy/terraform/modules/s3").exists(), (
        "modules/s3 came back; ADR 0001 renamed it to modules/object-storage"
    )


def test_delphi_structure_matches_its_adr() -> None:
    """core/llm/ carries the modules and dialect adapters ADR 0004 specifies."""
    for module in DELPHI_MODULES:
        assert (REPO_ROOT / "core" / "llm" / f"{module}.py").is_file(), (
            f"core/llm/{module}.py is missing"
        )
    for adapter in DELPHI_ADAPTERS:
        assert (REPO_ROOT / "core" / "llm" / "providers" / f"{adapter}.py").is_file(), (
            f"core/llm/providers/{adapter}.py is missing"
        )


def test_dialect_adapters_are_named_by_wire_format_not_vendor() -> None:
    """ADR 0004: a dialect outlives the vendor that popularised it."""
    vendor_named = {"openai", "anthropic", "google", "openai_compatible", "gemini"}
    present = {p.stem for p in (REPO_ROOT / "core" / "llm" / "providers").glob("*.py")}
    assert not (present & vendor_named), (
        f"vendor-named dialect adapters: {sorted(present & vendor_named)}"
    )


def test_delphi_is_not_an_agent() -> None:
    """Delphi is infrastructure: no roster entry, no manifest."""
    assert "delphi" not in AGENT_DOMAINS
    assert not (REPO_ROOT / "agents" / "delphi").exists()
    assert not (REPO_ROOT / "core" / "llm" / "manifest.yaml").exists()


# ---------------------------------------------------------------------------
# Credential policy - added on fix/generated-credential-policy
# ---------------------------------------------------------------------------

CHART = REPO_ROOT / "deploy" / "helm" / "pantheon"


def _values(name: str) -> dict[str, object]:
    import yaml

    loaded = yaml.safe_load((CHART / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_production_values_refuse_generated_credentials() -> None:
    """values-prod.yaml must fail closed rather than generate a credential.

    A generated credential is re-minted on every client-side render - `helm
    template`, `helm diff`, Argo CD's default mode - because `lookup` is empty
    there. Under GitOps that rotates the password on each sync and orphans the
    data encrypted against it.
    """
    prod = _values("values-prod.yaml")
    assert prod.get("productionMode") is True, (
        "values-prod.yaml must set productionMode: true so the chart fails closed"
    )

    minio = prod["minio"]
    assert isinstance(minio, dict)
    if minio.get("enabled"):
        assert minio.get("existingSecret"), "prod with bundled MinIO needs minio.existingSecret"
    else:
        external = minio["external"]
        assert isinstance(external, dict)
        assert external["existingSecret"], (
            "prod with external storage needs minio.external.existingSecret"
        )

    delphi = prod["delphi"]
    assert isinstance(delphi, dict)
    if delphi.get("enabled"):
        assert delphi.get("existingSecret"), "prod with Delphi enabled needs delphi.existingSecret"


def test_chart_has_a_validation_template_that_fails_closed() -> None:
    """The refusal is enforced by the chart, not only by the values file."""
    validation = (CHART / "templates" / "validation.yaml").read_text(encoding="utf-8")
    assert "fail" in validation, "validation.yaml must call `fail`"
    assert "productionMode" in validation
    for guarded in ("minio.existingSecret", "external.existingSecret", "delphi.existingSecret"):
        assert guarded in validation, f"validation.yaml does not guard {guarded}"


def test_generated_secret_is_marked_and_protected() -> None:
    """The generated secret is labelled dev-only and survives uninstall."""
    secret = (CHART / "templates" / "minio-secret.yaml").read_text(encoding="utf-8")
    assert "helm.sh/resource-policy: keep" in secret
    assert "pantheon.io/credential-policy: generated-dev-only" in secret
    assert "lookup" in secret and "client-side" in secret.lower(), (
        "the lookup caveat must stay documented at the point of use"
    )


def test_argocd_application_documents_client_side_rendering() -> None:
    """The trap is recorded where an operator would hit it."""
    app = (REPO_ROOT / "deploy" / "argocd" / "application.yaml").read_text(encoding="utf-8")
    assert "client-side" in app.lower()
    assert "productionMode" in app
