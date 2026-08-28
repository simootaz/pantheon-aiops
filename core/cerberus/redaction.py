"""Scrub secrets from logs, traces and prompts.

This module is **implemented, not stubbed**, unlike the rest of Cerberus. A
stubbed redactor cannot be tested, and an untested redactor is worse than none:
it creates the belief that secrets are being scrubbed while they are not.

Three sinks matter, and a secret must survive none of them:

- **logs**    - strings, persisted and often shipped off-box
- **traces**  - attribute mappings, exported to an OTel collector
- **prompts** - strings sent to an LLM provider and logged there too

The third is the reason Cerberus exists. A secret that reaches a prompt has left
the building: it is in a third party's logs, unauditable and unrevocable. See
docs/adr/0005-credential-brokering.md.

All three sinks are wired: `core/llm/tracing.py` redacts a prompt before it
reaches a span, `core/observability/logging.py` filters every log record, and
prompts are digested rather than carried.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

PLACEHOLDER = "[REDACTED]"

# Secrets shorter than this are not substring-replaced. A two-character "secret"
# would match half the corpus and redact everything, which destroys the logs
# without protecting anything.
MIN_LITERAL_LENGTH = 6

# Mapping keys whose *value* is always redacted, whatever it looks like.
_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|private[_-]?key|credential"
    r"|authorization|auth[_-]?header|session[_-]?id|cookie)",
    re.IGNORECASE,
)

# Keys that merely *reference* a credential are safe and must stay readable -
# redacting them would blind the audit trail this system depends on.
_REFERENCE_KEY = re.compile(r"(_ref|_id|_name|_type|_mode|_count)$", re.IGNORECASE)

# Shapes that are secret regardless of where they appear.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private key blocks, including the body.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        PLACEHOLDER,
    ),
    # Credentials embedded in a URL: scheme://user:password@host
    (
        re.compile(r"(?P<scheme>[a-zA-Z][\w+.-]*://)[^\s:/@]+:[^\s:/@]+@"),
        r"\g<scheme>" + PLACEHOLDER + "@",
    ),
    # Authorization headers, any scheme.
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+|basic\s+)?\S+"), r"\1" + PLACEHOLDER),
    # Bare bearer tokens.
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "bearer " + PLACEHOLDER),
    # JWTs.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"), PLACEHOLDER),
    # key=value / key: value assignments of sensitive names.
    (
        re.compile(
            r"(?i)\b((?:pass(?:word|wd|phrase)?|secret|token|api[_-]?key|private[_-]?key)"
            r"\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\1" + PLACEHOLDER,
    ),
)


def _redact_text(text: str, literals: Sequence[str]) -> str:
    """Remove known literals first, then anything secret-shaped."""
    for literal in literals:
        if len(literal) >= MIN_LITERAL_LENGTH:
            text = text.replace(literal, PLACEHOLDER)

    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)

    return text


def _known_literals(secrets: Iterable[str] | None) -> list[str]:
    """Longest first, so a secret containing another is replaced whole."""
    if not secrets:
        return []
    return sorted({s for s in secrets if s}, key=len, reverse=True)


def redact(value: Any, secrets: Iterable[str] | None = None) -> Any:
    """Return `value` with secrets removed, preserving its shape.

    Handles the three sink shapes with one entry point: a string (a log line or
    a prompt), a mapping (trace attributes), or a sequence of either.

    `secrets` are known plaintext values - typically supplied by the store for
    credentials currently leased - which are replaced literally. Pattern-based
    redaction runs regardless, so an unknown secret of a recognisable shape is
    still caught.

    Redaction is best-effort by nature: it is the last line of defence, not the
    first. The first is never giving an agent the secret at all.
    """
    literals = _known_literals(secrets)
    return _redact(value, literals)


def _redact(value: Any, literals: Sequence[str]) -> Any:
    if isinstance(value, str):
        return _redact_text(value, literals)

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _SENSITIVE_KEY.search(name) and not _REFERENCE_KEY.search(name):
                redacted[key] = PLACEHOLDER
            else:
                redacted[key] = _redact(item, literals)
        return redacted

    if isinstance(value, (list, tuple, set)):
        rebuilt = [_redact(item, literals) for item in value]
        if isinstance(value, tuple):
            return tuple(rebuilt)
        if isinstance(value, set):
            return set(rebuilt)
        return rebuilt

    return value


def contains_secret(value: Any, secrets: Iterable[str]) -> bool:
    """True if any known secret survives in `value`. For tests and assertions."""
    literals = [s for s in secrets if s]
    if not literals:
        return False
    haystack = repr(value)
    return any(literal in haystack for literal in literals)


# TODO: Phase 3 - source known literals from the Cerberus store for live leases
