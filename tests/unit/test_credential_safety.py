"""The invariants that make Cerberus worth having.

Three independent guards, each catching what the others cannot:

1. **Contract surface** - no generated type, in any language, has a property
   that could hold a secret. Run against the JSON Schema *and* the Go and
   TypeScript output, because the point is that it holds everywhere.
2. **Import graph** - nothing under ``agents/`` can import the modules that
   produce or hold plaintext. A contract check alone would miss an agent
   importing the store directly and never serialising anything.
3. **Redaction** - a planted secret survives none of the three sinks.

Guards 1 and 3 are **not** redundant, and neither subsumes the other. The schema
scan reads *field names*: it catches a model that declares somewhere to put a
secret. Redaction reads *values*: it catches a secret pasted into a field whose
name is entirely innocent - a Text component's body, a log line, a prompt. A
contract can pass the scan and still carry a secret, so removing either guard
leaves a real half of the threat uncovered.

See docs/adr/0005-credential-brokering.md.

Phase: 0 - Scaffold & Tooling
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from core.cerberus.redaction import PLACEHOLDER, contains_secret, redact
from tests.mechanism import read_data, read_mechanism, read_verbatim

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA = REPO_ROOT / "core/contracts/export/pantheon.schema.json"
GO_CONTRACTS = REPO_ROOT / "pkg/contracts/contracts.gen.go"
TS_CONTRACTS = REPO_ROOT / "dashboard/types/generated/contracts.ts"

# Substrings that mark a property as potentially secret-bearing.
SECRET_TOKENS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "privatekey",
    "credential",
    "plaintext",
    "cookie",
    "authorization",
)

# A property carrying one of the tokens above is allowed only if it is clearly a
# *reference* rather than a value.
REFERENCE_SUFFIXES = ("ref", "id", "name", "type", "mode", "count", "at", "by")

# Homographs: names that contain a secret token but mean something else. LLM
# token *counts* are the obvious case - "token" there is a unit of text, not a
# credential. Kept as a short explicit list rather than a cleverer regex, so
# every exemption is visible and reviewable.
SAFE_NAMES = frozenset(
    {
        "maxtokens",
        "mintokens",
        "totaltokens",
        "prompttokens",
        "completiontokens",
        "inputtokens",
        "outputtokens",
        "tokencount",
        # LLM token ACCOUNTING, added with AgentAccounting. A count and a
        # ceiling are integers; neither can carry a credential, and the guard
        # matches the substring rather than the type.
        "tokensspent",
        "tokenceiling",
    }
)

# Modules that produce or hold plaintext. Agents must not import these.
FORBIDDEN_FOR_AGENTS = (
    "core.cerberus.redemption",
    "core.cerberus.store",
    # Same boundary, different capability: this one turns an ArtifactRef into a
    # fetchable signed URL. An agent that could resolve could also read the
    # result, which is the exfiltration path ArtifactRef exists to close.
    "core.ui.artifact_resolution",
)

ALLOWED_FOR_AGENTS = (
    "core.cerberus.broker",
    "core.cerberus.redaction",
)


def _normalise(name: str) -> str:
    """Lowercase and strip separators so Go, TS and JSON names compare alike."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _is_secret_shaped(name: str) -> bool:
    flat = _normalise(name)
    if flat in SAFE_NAMES:
        return False
    if not any(token in flat for token in SECRET_TOKENS):
        return False
    return not flat.endswith(REFERENCE_SUFFIXES)


def test_the_heuristic_itself_behaves() -> None:
    """Pin the detector in both directions, so exemptions cannot creep."""
    for secret_shaped in ("password", "api_key", "SecretKey", "private_key", "authorization"):
        assert _is_secret_shaped(secret_shaped), f"{secret_shaped} should be flagged"
    for safe in (
        "credential_ref",
        "secret_ref",
        "max_tokens",
        "tokens_spent",
        "token_ceiling",
        "lease_id",
        "granted_by",
    ):
        assert not _is_secret_shaped(safe), f"{safe} should not be flagged"


# ---------------------------------------------------------------------------
# 1. contract surface, in every language
# ---------------------------------------------------------------------------


def _schema_property_names() -> set[str]:
    schema: dict[str, Any] = json.loads(read_data(SCHEMA))
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(str(key) for key in properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return names


def test_json_schema_has_no_secret_bearing_property() -> None:
    """Plaintext has no contract representation, so it cannot be serialised."""
    offenders = sorted(name for name in _schema_property_names() if _is_secret_shaped(name))
    assert not offenders, (
        f"JSON Schema exposes secret-shaped properties: {offenders}. "
        "Credentials are referenced by CredentialRef, never carried."
    )


def test_generated_go_has_no_secret_bearing_field() -> None:
    """The same invariant, checked on the Go artifact agents' connectors use."""
    fields = re.findall(r"^\t(\w+)\s+\S+.*`json:", read_mechanism(GO_CONTRACTS), re.M)
    offenders = sorted({name for name in fields if _is_secret_shaped(name)})
    assert not offenders, f"generated Go exposes secret-shaped fields: {offenders}"


def test_generated_typescript_has_no_secret_bearing_field() -> None:
    """And on the artifact the dashboard renders."""
    body = read_mechanism(TS_CONTRACTS)
    fields = re.findall(r"^\s{2,}(\w+)\??:\s", body, re.M)
    offenders = sorted({name for name in fields if _is_secret_shaped(name)})
    assert not offenders, f"generated TypeScript exposes secret-shaped fields: {offenders}"


def test_no_credential_value_contract_exists() -> None:
    """There is deliberately no model that *could* carry plaintext."""
    schema = json.loads(read_data(SCHEMA))
    defs = {name.lower() for name in schema.get("$defs", {})}
    for banned in ("credentialvalue", "credentialsecret", "plaintextcredential"):
        assert banned not in defs, (
            f"{banned} exists as a contract; plaintext must have no contract representation"
        )
    assert "credentialref" in defs, (
        "CredentialRef is missing; contracts cannot reference credentials"
    )


# ---------------------------------------------------------------------------
# 2. import graph
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by a file, however it was written."""
    tree = ast.parse(read_data(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            # `from core.cerberus import store` names the submodule in the alias.
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_agents_cannot_import_plaintext_modules() -> None:
    """Enforce the boundary at the import graph, not only at the contract surface.

    An agent that imported the store directly would never need to serialise a
    secret to leak it - it would simply have it in context, which is the exact
    failure this system exists to prevent.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "agents").rglob("*.py")):
        for module in _imported_modules(path):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_FOR_AGENTS
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")
    assert not offenders, "agents must not import plaintext-bearing modules:\n  " + "\n  ".join(
        offenders
    )


def test_allowed_import_surface_is_documented() -> None:
    """Each boundary is stated in its own package, where a developer would look."""
    from core.cerberus import AGENT_IMPORTABLE

    assert set(AGENT_IMPORTABLE) == set(ALLOWED_FOR_AGENTS)

    for forbidden in FORBIDDEN_FOR_AGENTS:
        package = ".".join(forbidden.split(".")[:2])  # e.g. core.cerberus, core.ui
        init = REPO_ROOT / package.replace(".", "/") / "__init__.py"
        assert init.is_file(), f"{package} has no __init__.py to document {forbidden}"
        documented = read_verbatim(
            init, why="this asserts the boundary is written down, which is prose"
        )
        assert forbidden in documented, (
            f"{forbidden} is not documented as off limits in {package}/__init__.py"
        )


# ---------------------------------------------------------------------------
# 3. redaction
# ---------------------------------------------------------------------------

PLANTED = "hunter2-s3cr3t-Pa55phrase-9f2b"


def test_planted_secret_survives_none_of_the_three_sinks() -> None:
    """Plant a known secret; assert it appears in no log, trace or prompt."""
    log_line = f"connecting to postgres://svc:{PLANTED}@db-01:5432/pantheon"
    trace_attributes = {
        "db.system": "postgresql",
        "db.password": PLANTED,
        "credential_ref": "cred-1234",
        "nested": {"api_key": PLANTED},
    }
    prompt = (
        "You are Argus. Investigate the outage.\n"
        f"Context: the operator supplied the password {PLANTED} for prod-postgres.\n"
        "Explain the anomaly."
    )

    redacted_log = redact(log_line, secrets=[PLANTED])
    redacted_trace = redact(trace_attributes, secrets=[PLANTED])
    redacted_prompt = redact(prompt, secrets=[PLANTED])

    assert not contains_secret(redacted_log, [PLANTED]), redacted_log
    assert not contains_secret(redacted_trace, [PLANTED]), redacted_trace
    assert not contains_secret(redacted_prompt, [PLANTED]), redacted_prompt

    assert PLACEHOLDER in redacted_log
    assert PLACEHOLDER in redacted_prompt


def test_redaction_catches_unknown_secrets_by_shape() -> None:
    """An unknown secret of a recognisable shape is still removed."""
    unknown = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijklmnop"
    assert unknown not in redact(f"Authorization: Bearer {unknown}")

    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
    assert "MIIEowIBAAKCAQEA" not in redact(f"key material:\n{pem}\n")


def test_redaction_preserves_references_and_shape() -> None:
    """Redaction must not blind the audit trail it protects."""
    attributes = {
        "credential_ref": "cred-1234",
        "investigation_id": "inv-99",
        "lease_id": "lease-7",
        "api_key": "should-vanish",
    }
    result = redact(attributes)

    assert result["credential_ref"] == "cred-1234"
    assert result["investigation_id"] == "inv-99"
    assert result["lease_id"] == "lease-7"
    assert result["api_key"] == PLACEHOLDER
    assert isinstance(result, dict)


def test_short_secrets_are_not_substring_replaced() -> None:
    """A tiny 'secret' would otherwise redact half the corpus."""
    text = "the cat sat on the mat"
    assert redact(text, secrets=["cat"]) == text


def test_schema_contains_no_nullable_enum() -> None:
    """A nullable enum breaks Go generation - catch it here, with an explanation.

    `X | None` on an enum exports as `anyOf: [{$ref: Enum}, {type: null}]`, and
    go-jsonschema v0.24.1 turns that into two conflicting UnmarshalJSON methods
    on one type. The package then fails to compile with an error that says
    nothing about the contract that caused it.

    Model absence as an explicit enum member instead - see
    CredentialAction.NOT_APPLICABLE.
    """
    schema = json.loads(read_data(SCHEMA))
    defs = schema.get("$defs", {})
    enums = {name for name, body in defs.items() if body.get("enum")}

    offenders: list[str] = []
    for owner, body in defs.items():
        for prop, spec in (body.get("properties") or {}).items():
            branches = spec.get("anyOf") or []
            refs = {str(b.get("$ref", "")).rsplit("/", 1)[-1] for b in branches}
            nullable = any(b.get("type") == "null" for b in branches)
            if nullable and refs & enums:
                offenders.append(f"{owner}.{prop} -> {sorted(refs & enums)}")

    assert not offenders, (
        "nullable enums break Go codegen (duplicate UnmarshalJSON): "
        f"{offenders}. Add an explicit member such as NOT_APPLICABLE instead."
    )
