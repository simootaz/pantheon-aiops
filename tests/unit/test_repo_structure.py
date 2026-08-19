"""Structural guards for the repository scaffold.

Phase 0 delivers a structure, so the structure is what Phase 0 tests. These
guards fail loudly if a future change breaks an invariant that
docs/REPOSITORY_MAP.md promises: the agent roster, package initialisers, phase
markers on every module, and the do-not-edit banner on generated directories.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.mechanism import read_data, read_mechanism, read_verbatim

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
        source = read_verbatim(path, why="phase markers are comments")
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
        banner = read_verbatim(readme, why="the do-not-edit banner is prose")
        assert "do not edit" in banner.lower()


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
        head = read_verbatim(REPO_ROOT / relative, why="the generated-by banner is a comment")[
            :400
        ].lower()
        assert "generated" in head, f"{relative} does not announce that it is generated"
        assert "do not edit" in head or "not edit" in head, (
            f"{relative} does not warn against hand-editing"
        )


def test_line_endings_are_enforced_repository_wide() -> None:
    """`.gitattributes` makes LF a property of the repo, not of each clone.

    Checks the **index**, not the working tree. A working copy may legitimately
    hold CRLF - that is what checkout does on some platforms - but a committed
    blob with CRLF is the defect, because it is what every other clone receives.

    Without `.gitattributes` this depends on each contributor's local
    `core.autocrlf`. That is a coincidence, not a guarantee: it holds until
    someone clones with Windows' default of `true` and commits CRLF. A shell
    script that acquires CRLF fails with `bad interpreter: No such file or
    directory`, which is a genuinely confusing way to spend an afternoon.
    """
    attributes = REPO_ROOT / ".gitattributes"
    assert attributes.is_file(), ".gitattributes is missing; LF is not enforced"

    declared = read_mechanism(attributes)
    assert re.search(r"^\*\s+text=auto\s+eol=lf\s*$", declared, re.MULTILINE), (
        ".gitattributes does not declare `* text=auto eol=lf`, so normalisation "
        "falls back to each contributor's core.autocrlf"
    )
    for extension in (".sh", ".py", ".go", ".ts"):
        assert re.search(rf"^\*{re.escape(extension)}\s+text\s+eol=lf", declared, re.MULTILINE), (
            f"{extension} files are not explicitly pinned to LF"
        )

    listing = subprocess.run(
        ["git", "ls-files", "--eol"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout

    offenders: list[str] = []
    for line in listing.splitlines():
        if not line.strip():
            continue
        index_eol, _, remainder = line.partition(" ")
        if "crlf" in index_eol or "mixed" in index_eol:
            offenders.append(f"{remainder.split()[-1]} ({index_eol})")

    assert not offenders, (
        "tracked files carry CRLF in the index:\n  "
        + "\n  ".join(offenders)
        + "\nRun `git add --renormalize .` and commit."
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

    loaded = yaml.safe_load(read_data(CHART / name))
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
    body = read_mechanism(CHART / "templates" / "validation.yaml")

    calls = re.findall(r"\{\{-?\s*fail\s", body)
    assert len(calls) >= 3, (
        f"validation.yaml makes {len(calls)} fail() calls; one is needed per guarded "
        "credential (bundled MinIO, external storage, Delphi)"
    )
    assert "productionMode" in body
    for guarded in ("minio.existingSecret", "external.existingSecret", "delphi.existingSecret"):
        assert guarded in body, f"validation.yaml does not guard {guarded}"


def test_generated_secret_is_marked_and_protected() -> None:
    """The generated secret is labelled dev-only and survives uninstall.

    The annotations are checked against the template body with comments removed,
    because this file's header *describes* `resource-policy: keep` - so a check
    against the whole file passes even after the real annotation is deleted.
    """
    secret = CHART / "templates" / "minio-secret.yaml"
    body = read_mechanism(secret)
    raw = read_verbatim(secret, why="the lookup caveat is documentation, asserted as such")

    for annotation in (
        "helm.sh/resource-policy: keep",
        "pantheon.io/credential-policy: generated-dev-only",
        "argocd.argoproj.io/compare-options",
    ):
        assert annotation in body, f"minio-secret.yaml no longer sets {annotation}"

    # The caveat is documentation, so it is checked against the raw file.
    assert "lookup" in raw and "client-side" in raw.lower(), (
        "the lookup caveat must stay documented at the point of use"
    )


def test_argocd_application_documents_client_side_rendering() -> None:
    """The trap is recorded where an operator would hit it.

    Checks the whole warning, not just the phrase: one incidental mention of
    "client-side" elsewhere in the file would otherwise satisfy this while the
    explanation an operator needs had been deleted.
    """
    app = read_verbatim(
        REPO_ROOT / "deploy" / "argocd" / "application.yaml",
        why="this guard asserts the operator-facing warning text itself",
    )
    lowered = app.lower()

    for required in (
        "client-side",
        "productionmode",
        "lookup",  # names the mechanism, not just the symptom
        "rotat",  # rotating the password on each sync is the actual consequence
    ):
        assert required in lowered, (
            f"deploy/argocd/application.yaml no longer explains {required!r}; "
            "the client-side rendering trap must stay documented in full"
        )


# ---------------------------------------------------------------------------
# Cerberus and licensing - added on feature/cerberus-credential-brokering
# ---------------------------------------------------------------------------

CERBERUS_MODULES = ("broker", "lease", "redemption", "redaction")
CERBERUS_HEADS = {
    "store": ("vault", "envelope", "master_key", "kinds", "rotation"),
    "policy": ("grants", "modes", "scope", "defaults", "revocation"),
    "audit": ("log", "attach"),
}


def test_cerberus_structure_matches_its_adr() -> None:
    """Three heads, plus the broker, lease, redemption and redaction modules."""
    base = REPO_ROOT / "core" / "cerberus"
    for module in CERBERUS_MODULES:
        assert (base / f"{module}.py").is_file(), f"core/cerberus/{module}.py is missing"
    for head, modules in CERBERUS_HEADS.items():
        assert (base / head / "__init__.py").is_file(), f"core/cerberus/{head}/ is not a package"
        for module in modules:
            assert (base / head / f"{module}.py").is_file(), (
                f"core/cerberus/{head}/{module}.py is missing"
            )


def test_cerberus_is_not_an_agent() -> None:
    """Infrastructure, like Delphi: no roster entry, no manifest."""
    assert "cerberus" not in AGENT_DOMAINS
    assert not (REPO_ROOT / "agents" / "cerberus").exists()
    assert not (REPO_ROOT / "core" / "cerberus" / "manifest.yaml").exists()


def test_delphi_no_longer_ships_its_own_secret_store() -> None:
    """ADR 0005: provider keys are Cerberus credentials, and no shim was left.

    A re-export shim would leave two apparent secret stores in the tree, and
    someone would eventually reach for the wrong one.
    """
    assert not (REPO_ROOT / "core" / "llm" / "keyring.py").exists(), (
        "core/llm/keyring.py is back; provider keys belong in Cerberus"
    )


def test_license_is_apache_2_consistently() -> None:
    """One licence, stated the same way everywhere it is stated."""
    licence = read_verbatim(REPO_ROOT / "LICENSE", why="the licence body is prose")
    assert "Apache License" in licence

    pyproject = read_mechanism(REPO_ROOT / "pyproject.toml")
    assert 'license = "Apache-2.0"' in pyproject
    assert "MIT" not in pyproject

    chart = read_mechanism(CHART / "Chart.yaml")
    assert "Apache-2.0" in chart

    readme = read_verbatim(REPO_ROOT / "README.md", why="the licence section is prose")
    assert "Apache" in readme and "LICENSE" in readme

    # The dashboard is scaffolded on a later branch; assert as soon as it exists.
    package_json = REPO_ROOT / "dashboard" / "package.json"
    if package_json.is_file():
        import json

        assert json.loads(read_data(package_json)).get("license") == "Apache-2.0"


# --- countable claims in the README ------------------------------------------

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _readme_number(pattern: str) -> int:
    """The number the README claims, as a digit or as an English word."""
    match = re.search(pattern, read_data(REPO_ROOT / "README.md"), re.IGNORECASE)
    assert match, f"the README no longer makes the claim matched by {pattern!r}"
    raw = match.group(1)
    return int(raw) if raw.isdigit() else _NUMBER_WORDS[raw.lower()]


#: Every typed count of a repository artifact, and how to derive the truth.
#: Keyed by the document, so a claim cannot be moved to another file to escape.
_COUNTED = "counted"


def _count_models() -> int:
    return sum(
        len(re.findall(r"^class [A-Za-z0-9_]+\(ContractModel\):", read_data(path), re.MULTILINE))
        for path in sorted((REPO_ROOT / "core" / "contracts").glob("*.py"))
    )


def _count_tests() -> int:
    return sum(
        len(re.findall(r"^def test_", read_data(path), re.MULTILINE))
        for path in sorted((REPO_ROOT / "tests").rglob("test_*.py"))
    )


def _count_dirs(parent: str) -> int:
    root = REPO_ROOT / parent
    return len(
        [
            child
            for child in root.iterdir()
            if child.is_dir() and not child.name.startswith(("_", "."))
        ]
    )


def test_every_typed_count_in_the_docs_is_true() -> None:
    """A number in prose is a claim, and it goes stale in total silence.

    These were the last thing the "X is guarded" audit found, because a number
    does not read like a mechanism claim at all. They were the most wrong:
    **19** contract models against 49, and **78** guards against 279 tests -
    in the two most-read files in the repository, for weeks.

    Fixing the README alone was not enough. The same two numbers had been
    copied into `ARCHITECTURE.md` and `ROADMAP.md`, which the first pass did
    not look at because they were not on the list of files to audit. Copies of
    a claim do not stay together; that is the argument for deriving all of them
    in one place rather than checking the file someone remembered.

    The workflow, ADR, module and scenario counts were all accurate when this
    was written, which is the point. Being right today is not the property
    worth having.
    """
    actual = {
        "models": _count_models(),
        "tests": _count_tests(),
        "workflows": len(list((REPO_ROOT / ".github" / "workflows").glob("*.yml"))),
        "adrs": len(list((REPO_ROOT / "docs" / "adr").glob("0*.md"))),
        "go_modules": len([p for p in REPO_ROOT.rglob("go.mod") if "node_modules" not in p.parts]),
        "scenarios": len(list((REPO_ROOT / "simulator" / "scenarios").glob("*.yaml"))),
        "agents": _count_dirs("agents"),
        "connectors": _count_dirs("connectors"),
    }

    # (document, regex capturing the number, which count it must equal)
    claims: list[tuple[str, str, str]] = [
        ("README.md", r"\*\*Contracts\*\*[^|]*?(\d+) Pydantic", "models"),
        ("README.md", r"\*\*(\d+) tests\*\*", "tests"),
        ("README.md", r"\*\*CI\*\*[^|]*?(\d+) workflows", "workflows"),
        ("README.md", r"\*\*(\w+) ADRs\*\*", "adrs"),
        ("README.md", r"\|\s*\[docs/adr/\]\([^)]*\)\s*\|\s*(\w+) decision records", "adrs"),
        ("ARCHITECTURE.md", r"\*\*(\d+) tests\*\*", "tests"),
        ("ROADMAP.md", r"\|\s*Contracts\s*\|\s*(\d+) models", "models"),
        ("ROADMAP.md", r"\|\s*Go\s*\|\s*workspace over (\d+) modules", "go_modules"),
        ("ROADMAP.md", r"\|\s*CI\s*\|\s*(\d+) workflows", "workflows"),
        ("ROADMAP.md", r"\|\s*Docs\s*\|\s*(\d+) ADRs", "adrs"),
        ("ROADMAP.md", r"Simulator:.*?(\w+) scenarios", "scenarios"),
        ("docs/REPOSITORY_MAP.md", r"Go workspace over the (\w+) Go modules", "go_modules"),
        ("docs/REPOSITORY_MAP.md", r"(\w+) YAML scenarios", "scenarios"),
        ("docs/REPOSITORY_MAP.md", r"\|\s*\*\*agents/\*\*\s*\|[^|]*?(\w+) domain agents", "agents"),
    ]

    wrong: list[str] = []
    for document, pattern, key in claims:
        match = re.search(pattern, read_data(REPO_ROOT / document), re.IGNORECASE)
        assert match, f"{document} no longer makes the claim matched by {pattern!r}"
        raw = match.group(1)
        claimed = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw.lower()]
        if claimed != actual[key]:
            wrong.append(f"{document} claims {claimed} {key}; there are {actual[key]}")

    assert not wrong, "typed counts that have gone stale:\n  " + "\n  ".join(wrong)


# --- the map's currency, which nothing had ever checked -----------------------


def _tracked_root_entries() -> list[str]:
    """Top-level names git tracks, files and directories alike."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    # ls-files, not ls-tree HEAD: the index includes files staged but not yet
    # committed, so the pre-commit hook catches a new entry at the moment it is
    # added rather than one commit later.
    return sorted({name.split("/")[0] for name in result.stdout.splitlines() if name.strip()})


def test_the_map_names_every_tracked_root_entry() -> None:
    """The README claimed a test made this impossible. There was no such test.

    CONTRIBUTING makes updating the map "part of every change", and the README
    says the map "cannot go stale without a test failing". The only test
    touching it asserted that it exists, is tracked, and carries certain
    headings - nothing about whether it is *current*.

    The proof arrived on this branch. `.trivyignore`,
    `dashboard/pnpm-workspace.yaml` and `tests/unit/test_ci_is_runnable.py`
    were added and committed without appearing in the map, and the full suite
    stayed green through three commits. It was caught by reading, late, which
    is exactly the mechanism the rule exists to replace.
    """
    body = read_data(REPO_ROOT / "docs" / "REPOSITORY_MAP.md")
    missing = [entry for entry in _tracked_root_entries() if entry not in body]
    assert not missing, (
        "tracked top-level entries the repository map never mentions:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd them to the folder map in the same commit that created them."
    )


def test_the_folder_map_draws_nothing_that_no_longer_exists() -> None:
    """The other direction: a map naming a deleted path misleads harder than silence.

    Scoped to the folder-map tree, which is the part describing what exists.
    The first version scanned every backticked path in the file and reported
    ten deletions, of which none were defects: `api/ws/` and
    `core/llm/keyring.py` appear in the **structure changelog**, whose entries
    read "Deleted `api/ws/`" - a changelog is supposed to name things that are
    gone. Others were future paths carrying a later phase number.

    A guard whose failures are mostly noise gets read as noise, so it asserts
    over the one section where a missing path is unambiguously wrong.
    """
    body = read_data(REPO_ROOT / "docs" / "REPOSITORY_MAP.md")
    block = re.search(r"```" + chr(10) + r"(pantheon-aiops/.*?)```", body, re.DOTALL)
    assert block, "the folder-map tree is gone from docs/REPOSITORY_MAP.md"

    drawn: list[str] = []
    for line in block.group(1).splitlines()[1:]:
        stripped = re.sub(
            r"^[\s|]*[" + chr(0x251C) + chr(0x2514) + chr(0x2502) + chr(0x2500) + r"]+\s*", "", line
        ).strip()
        if stripped:
            drawn.append(stripped.split()[0])

    assert len(drawn) >= 10, f"the folder map draws only {len(drawn)} entries; has it been gutted?"
    gone = sorted(name for name in drawn if not (REPO_ROOT / name).exists())
    assert not gone, (
        "entries the folder map draws that do not exist: "
        + ", ".join(gone)
        + " - either restore them or correct the map."
    )
