"""`core/config.py` is the only thing that reads the environment.

Every scattered `os.environ.get("PROMETHEUS_URL", "http://localhost:9090")` is
two failures waiting. Dev and prod diverge silently when one call site learns a
new variable and another keeps its default. And a typo — `PROMETEUS_URL` — falls
back to something that looks like it works, forever.

Centralising it only helps if it stays centralised, which is what these guards
are for. The first one is load-bearing: everything else in this file is checking
that the single source of truth is complete and honest, but that guard is what
keeps it single.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from core.config import OPTIONAL_IN_PRODUCTION, REQUIRED_IN_PRODUCTION, Settings
from tests.mechanism import read_data, read_verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPO_ROOT / "core" / "config.py"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: Python the platform ships. Tests and codegen are excluded deliberately: a
#: test may need to set an environment variable to exercise the config module
#: itself, and codegen emits schema identifiers rather than endpoints.
SOURCE_DIRS = ("core", "agents", "api", "connectors", "simulator")

#: URL literals that are not configuration, with the reason each is allowed.
ALLOWED_URLS: dict[str, str] = {
    "https://gitlab.example.com": "sample payload data in a GitLab webhook fixture",
    "http://localhost:9090": "the documented default, defined in core/config.py",
    "http://localhost:3100": "the documented default, defined in core/config.py",
    "http://localhost:9091": "the documented default, defined in core/config.py",
    "http://localhost:9093": "the documented default, defined in core/config.py",
    "http://localhost:4317": "the documented default, defined in core/config.py",
    "http://localhost:8000/webhooks/gitlab": "the documented default, in core/config.py",
    "http://minio:9000": "the documented default, defined in core/config.py",
    "http://ollama:11434/v1": "the documented default, defined in core/config.py",
    "https://gitlab.com": "the documented default, defined in core/config.py",
}

#: Variables in .env.example that no Python setting reads, and why.
NON_PYTHON_VARIABLES: dict[str, str] = {
    "NEXT_PUBLIC_API_URL": "consumed by Next.js at build time; the dashboard owns it",
}

URL_LITERAL = re.compile(r"https?://[^\s\"'<>)]+")

#: URLs used as *identifiers*, never dialled. A schema `$id` and a UUIDv5
#: namespace are both URL-shaped by specification, and neither is an endpoint
#: anyone configures. `.local` is reserved and not routable, which is precisely
#: why it is the right choice for a namespace constant.
IDENTIFIER_URLS: tuple[str, ...] = (
    "json-schema.org",
    "github.com/simootaz",
    "pantheon.local",
)


def python_sources() -> list[Path]:
    return sorted(
        path
        for directory in SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*.py")
        if path.resolve() != CONFIG.resolve()
    )


def env_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """Calls that pull a value out of the process environment."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            found.append((node.lineno, f"os.{node.attr}"))
        elif isinstance(node, ast.Name) and node.id == "environ":
            found.append((node.lineno, "environ"))
    return found


# --- the load-bearing one ----------------------------------------------------


@pytest.mark.parametrize("module", python_sources(), ids=lambda p: p.name)
def test_only_the_config_module_reads_the_environment(module: Path) -> None:
    """One reader, so a variable cannot be half-renamed across the codebase."""
    source = read_data(module)
    offenders = env_reads(ast.parse(source))
    assert not offenders, (
        f"{module.relative_to(REPO_ROOT)} reads the environment at "
        + ", ".join(f"line {line} ({what})" for line, what in offenders)
        + ". Add a field to core/config.py and read it from get_settings() instead."
    )


def test_the_scanner_sees_every_shape_of_environment_read() -> None:
    """Both directions on the scanner, since it is the whole guard."""
    for source in (
        'import os\nos.environ.get("X")',
        'import os\nos.environ["X"]',
        'import os\nos.getenv("X")',
        'from os import environ\nenviron.get("X")',
    ):
        assert env_reads(ast.parse(source)), f"the scanner cannot see: {source!r}"

    clean = "from core.config import get_settings\nget_settings().prometheus.base"
    assert not env_reads(ast.parse(clean)), "the scanner fires on a settings lookup"


# --- no endpoint written down twice ------------------------------------------


@pytest.mark.parametrize("module", python_sources(), ids=lambda p: p.name)
def test_no_hardcoded_endpoint_outside_the_config_module(module: Path) -> None:
    """A URL in the code is a default nobody can override from the environment."""
    offenders: list[str] = []
    for node in ast.walk(ast.parse(read_data(module))):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        for found in URL_LITERAL.findall(node.value):
            url = found.rstrip("/")
            if url in ALLOWED_URLS or any(url.startswith(base) for base in ALLOWED_URLS):
                continue
            if any(marker in url for marker in IDENTIFIER_URLS):
                continue
            offenders.append(f"line {node.lineno}: {url}")

    assert not offenders, (
        f"{module.relative_to(REPO_ROOT)} hardcodes " + ", ".join(offenders) + ". "
        "Endpoints belong in core/config.py so they can differ between "
        "environments without an edit."
    )


# --- the template and the model agree, both ways -----------------------------


def declared_variables(model: type[BaseSettings], prefix: str = "") -> set[str]:
    """Every environment variable the settings model can read."""
    names: set[str] = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseSettings):
            nested: str = annotation.model_config.get("env_prefix", "")
            names |= declared_variables(annotation, nested)
        else:
            names.add(f"{prefix}{name}".upper())
    return names


def template_variables() -> set[str]:
    body = read_verbatim(ENV_EXAMPLE, why="the commented sections are the documentation")
    return {
        match.group(1)
        for line in body.splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()))
    }


def test_every_setting_has_an_entry_in_the_template() -> None:
    """A field with no entry is a knob nobody knows exists."""
    missing = sorted(
        declared_variables(Settings, Settings.model_config.get("env_prefix", ""))
        - template_variables()
    )
    assert not missing, (
        f".env.example has no entry for: {missing}. A setting absent from the "
        "template is one an operator will never think to set."
    )


def test_every_template_entry_maps_to_a_setting() -> None:
    """The other direction: an entry nothing reads is a lie about the system."""
    declared = declared_variables(Settings, Settings.model_config.get("env_prefix", ""))
    stale = sorted(template_variables() - declared - set(NON_PYTHON_VARIABLES))
    assert not stale, (
        f".env.example documents variables nothing reads: {stale}. Either add a "
        "field to core/config.py or delete the entry — a template that promises "
        "a knob which does nothing is worse than no template."
    )


# --- secrets fail closed -----------------------------------------------------


@pytest.mark.parametrize(("group", "field", "variable"), REQUIRED_IN_PRODUCTION)
def test_a_missing_secret_fails_at_startup_in_production(
    group: str, field: str, variable: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent means refuse to start, not fall back to a development value."""
    for _group, _field, other in REQUIRED_IN_PRODUCTION:
        monkeypatch.setenv(other, "" if other == variable else "set-for-this-test")
    monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("PANTHEON_ENV", "production")

    with pytest.raises(ValueError, match=variable):
        Settings()


def test_the_same_secrets_are_optional_outside_production() -> None:
    """`make up` has to work with no .env at all, or nobody will run it."""
    settings = Settings()
    assert settings.postgres.password is None
    assert settings.object_storage.secret_key is None


def test_a_secret_is_never_printed_by_accident() -> None:
    """SecretStr, so a settings dump in a log does not leak the value."""
    settings = Settings.model_validate({"gitlab": {"token": "hunter2"}})
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.gitlab.token)
    assert settings.gitlab.token is not None
    assert settings.gitlab.token.get_secret_value() == "hunter2"


# --- Go reads the same names -------------------------------------------------

GO_ENV_READ = re.compile(r'os\.(?:Getenv|LookupEnv)\(\s*"([A-Z][A-Z0-9_]*)"')


def go_environment_reads() -> list[tuple[Path, str]]:
    return [
        (path, name)
        for path in sorted(REPO_ROOT.rglob("*.go"))
        if "generated" not in path.parts
        for name in GO_ENV_READ.findall(read_data(path))
    ]


def test_go_modules_read_variables_the_template_declares() -> None:
    """A Go connector on PROM_URL while Python is on PROMETHEUS_URL is the bug.

    The Go modules read nothing today, so this guard has no live subjects yet —
    stated plainly rather than left to look like coverage it does not have. It
    is verified by planting a Go file that reads an undeclared name, so it will
    work the moment the Kubernetes connector starts configuring itself.
    """
    known = template_variables()
    offenders = [
        f"{path.relative_to(REPO_ROOT)} reads {name}"
        for path, name in go_environment_reads()
        if name not in known
    ]
    assert not offenders, (
        "Go reads environment variables .env.example does not declare: "
        + "; ".join(offenders)
        + ". Python and Go must agree on the name or they configure different things."
    )


# --- the template holds placeholders, never values ---------------------------


def secret_variables(model: type[BaseSettings], prefix: str = "") -> set[str]:
    """Variables whose field is a SecretStr, so declared secrets, not guessed.

    An earlier version matched names containing KEY, SECRET, TOKEN and so on.
    It flagged `LLM_MAX_TOKENS` (a count) and `S3_ACCESS_KEY` (an identifier
    paired with the secret, not the secret). The model already records which
    fields are credentials; asking it is authoritative where a name heuristic
    is a guess.
    """
    names: set[str] = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseSettings):
            names |= secret_variables(annotation, annotation.model_config.get("env_prefix", ""))
        elif SecretStr in get_args(annotation) or annotation is SecretStr:
            names.add(f"{prefix}{name}".upper())
    return names


def template_entries() -> dict[str, str]:
    body = read_verbatim(ENV_EXAMPLE, why="asserting on the literal values in the template")
    return {
        match.group(1): match.group(2).strip()
        for line in body.splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.strip()))
    }


def test_the_template_never_carries_a_real_secret() -> None:
    """`.env.example` is excluded from gitleaks, so this covers it instead.

    The exclusion is a transfer of responsibility, not a removal: gitleaks'
    generic-api-key rule fires on `CERBERUS_MASTER_KEY=` on the variable name
    alone, and scoping its allowlist to empty assignments did not behave
    correctly when tested in both directions. `.gitleaks.toml` says so and
    points here.

    This is stricter than the heuristic it replaces, because it knows which
    variables are credentials rather than inferring it from entropy.
    """
    entries = template_entries()
    offenders = sorted(
        f"{name}={entries[name]!r}"
        for name in secret_variables(Settings, Settings.model_config.get("env_prefix", ""))
        if entries.get(name)
    )
    assert not offenders, (
        "the environment template carries real values for declared secrets: "
        + "; ".join(offenders)
        + ". .env.example holds empty placeholders only; a value here is committed "
        "to the repository and excluded from secret scanning."
    )


def test_every_declared_secret_appears_in_the_template() -> None:
    """A secret with no entry is one nobody knows they have to set."""
    entries = template_entries()
    missing = sorted(
        secret_variables(Settings, Settings.model_config.get("env_prefix", "")) - set(entries)
    )
    assert not missing, f"secrets absent from .env.example: {missing}"


# --- and anything that merely LOOKS like a credential ------------------------

#: High-confidence credential shapes, matched against values regardless of the
#: variable name. The name-based guard above only covers variables the settings
#: model declares as SecretStr; a credential pasted under a name that is not a
#: field - a stray GITHUB_TOKEN_OLD, a hand-added AWS key - would slip past both
#: it and gitleaks, since .env.example is excluded there. This closes that.
#:
#: Every pattern is a vendor-issued prefix or a structural marker, not a guess
#: about entropy, so a dev-shaped default like `qwen2.5:3b` cannot trip it.
CREDENTIAL_SHAPES: tuple[tuple[str, str], ...] = (
    (r"glpat-[A-Za-z0-9_-]{16,}", "GitLab personal access token"),
    (r"gh[pousr]_[A-Za-z0-9]{20,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained token"),
    (r"sk-[A-Za-z0-9_-]{20,}", "OpenAI-style API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"ASIA[0-9A-Z]{16}", "AWS temporary access key id"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"hf_[A-Za-z0-9]{30,}", "Hugging Face token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "PEM private key"),
    (r"[A-Za-z0-9+/]{40,}={0,2}", "long base64 run"),
    (r"[0-9a-fA-F]{40,}", "long hex run"),
)


def test_the_template_holds_nothing_shaped_like_a_credential() -> None:
    """Catches a pasted secret under a name no settings field declares.

    `.env.example` is excluded from gitleaks, and the guard above only knows
    about variables the model types as SecretStr. A credential added by hand
    under some other name - GITHUB_TOKEN_OLD, MY_KEY, a leftover from debugging
    - is exactly what a template collects, and would be caught by neither.

    So this matches vendor-issued shapes against every value, whatever it is
    called.
    """
    body = read_verbatim(ENV_EXAMPLE, why="scanning the literal values for credentials")

    offenders = []
    for number, line in enumerate(body.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        value = stripped.split("=", 1)[1] if "=" in stripped else stripped
        for pattern, what in CREDENTIAL_SHAPES:
            if re.search(pattern, value):
                offenders.append(f"line {number}: {what}")
                break

    assert not offenders, (
        "the environment template contains values shaped like real credentials: "
        + "; ".join(offenders)
        + ". .env.example is committed and excluded from gitleaks, so a secret "
        "here is a secret in the repository."
    )


def test_every_secret_is_classified_for_production() -> None:
    """The third step CONTRIBUTING promised a guard for, which had none.

    Four SecretStr fields had fallen outside REQUIRED_IN_PRODUCTION with
    nothing noticing - the existing tests iterate OVER that tuple, so they
    verify the entries present and say nothing about the ones missing. A guard
    that checks a list is not a guard that the list is complete.

    Forcing the partition means adding a credential is a decision, and an
    optional one has to say why.
    """
    declared = secret_variables(Settings, Settings.model_config.get("env_prefix", ""))
    required = {variable for _group, _field, variable in REQUIRED_IN_PRODUCTION}
    optional = set(OPTIONAL_IN_PRODUCTION)

    unclassified = sorted(declared - required - optional)
    assert not unclassified, (
        f"SecretStr fields classified neither required nor optional in production: "
        f"{unclassified}. Add a row to REQUIRED_IN_PRODUCTION, or an entry to "
        "OPTIONAL_IN_PRODUCTION saying why absence is acceptable."
    )

    both = sorted(required & optional)
    assert not both, f"classified as both required and optional: {both}"

    stale = sorted((required | optional) - declared)
    assert not stale, f"classified but no longer a SecretStr field: {stale}"


def test_every_optional_secret_states_why() -> None:
    """An entry with no reason is the classification skipped, not made."""
    for variable, reason in OPTIONAL_IN_PRODUCTION.items():
        assert len(reason.strip()) > 25, f"{variable} is optional with no real reason given"
