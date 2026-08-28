"""Structured logging, correlated by investigation, with secrets scrubbed.

`core/cerberus/redaction.py` has been implemented and tested since Phase 0, and
its own docstring says *"wiring these into the actual sinks is Phase 2-3 work"*.
Two of the three sinks were already wired: `core/llm/tracing.py` redacts a
prompt before it reaches a span, and prompts are digested rather than carried.

**Logs were not.** Nothing configured logging at all, and the one module that
uses it calls `logger.exception(...)` - which writes an exception's message
verbatim. A provider that returns `401 for key gsk_live_...` puts that string in
an exception, and the exception goes to a log that is often shipped off-box.

WHAT A FILTER CAN AND CANNOT DO
---------------------------------
This is the LAST line of defence, not the first. The first is never giving an
agent the secret at all - see ADR 0005.

Pattern redaction catches secret-SHAPED mappings: a dict with a key called
`api_key`, an `Authorization` header. It cannot catch a bare credential sitting
in a sentence, because a sentence has no keys.

So the configured secrets are registered as **literals**. Every `SecretStr` the
settings hold is collected once at configure time and replaced wherever it
appears, in any message, in any argument. That closes the case the pattern rules
cannot see, and it is why `configure()` reads settings rather than taking a list
- a list someone maintains by hand is a list that goes stale the first time a
credential is added.

A secret that was never configured is still not caught unless it is
recognisably shaped. That is stated rather than papered over: this reduces
blast radius, it does not make logging safe to be careless with.

CORRELATION
-------------
`investigation_id` travels on a `ContextVar`, so every line emitted during a run
carries it without being passed through twenty call signatures. A contextvar
rather than a thread-local because the runtime is asyncio and a thread-local is
shared by every task on the loop - which would attribute one investigation's
logs to another under any concurrency at all.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from core.cerberus.redaction import redact

#: The investigation every log line in this task belongs to, or None outside a run.
_INVESTIGATION: ContextVar[str | None] = ContextVar("investigation_id", default=None)

#: Record attributes that are logging's own furniture rather than payload. Kept
#: out of the JSON so a line is readable; everything else a caller attached with
#: `extra=` is carried through, redacted.
_STANDARD = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


@contextmanager
def investigation(investigation_id: UUID | str) -> Iterator[None]:
    """Tag every log line emitted inside this block with an investigation id.

    A context manager rather than a setter, so the tag is removed on the way out
    even when the block raises. A leaked tag attributes the NEXT investigation's
    lines to the previous one, which is worse than no correlation at all -
    absent correlation is visibly absent, wrong correlation is not.
    """
    token = _INVESTIGATION.set(str(investigation_id))
    try:
        yield
    finally:
        _INVESTIGATION.reset(token)


def configured_secrets() -> list[str]:
    """Every configured secret, as plaintext, for literal redaction.

    Read from settings rather than taken as an argument. A hand-maintained list
    is one that goes stale the first time a credential is added - and the
    failure mode is silent, because nothing looks different until the day that
    credential appears in a log.

    Returns plaintext by necessity: the filter has to compare against the real
    value. It is never returned anywhere else, and nothing here logs it.
    """
    from pydantic import BaseModel, SecretStr

    from core.config import get_settings

    found: list[str] = []

    def walk(model: BaseModel) -> None:
        for value in vars(model).values():
            if isinstance(value, SecretStr):
                plaintext = value.get_secret_value()
                if plaintext:
                    found.append(plaintext)
            elif isinstance(value, BaseModel):
                walk(value)

    walk(get_settings())
    return found


class RedactingFilter(logging.Filter):
    """Scrubs every record on its way to a handler.

    A filter rather than a formatter: a formatter runs per handler, so a second
    handler added later would emit unredacted lines, and the failure would look
    like a configuration difference rather than a leak.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        # Snapshotted at configure time. Re-reading settings per record would
        # put a settings lookup on every log line, and settings are cached
        # anyway - so it would be the same list at more cost.
        self._secrets = secrets if secrets is not None else configured_secrets()

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg, self._secrets)
        if record.args:
            record.args = _redact_args(record.args, self._secrets)

        # `exc_text` is the rendered traceback, and a provider's 401 body lands
        # in it verbatim. Rendered here so there is a string to scrub - leaving
        # it to the formatter would emit the raw one.
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = str(redact(record.exc_text, self._secrets))

        for key, value in list(vars(record).items()):
            if key not in _STANDARD and not key.startswith("_"):
                setattr(record, key, redact(value, self._secrets))
        return True


def _redact_args(args: Any, secrets: list[str]) -> Any:
    """Log args are a tuple or a single mapping; both need the same treatment."""
    if isinstance(args, tuple):
        return tuple(redact(arg, secrets) for arg in args)
    return redact(args, secrets)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the investigation id attached."""

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        investigation_id = _INVESTIGATION.get()
        if investigation_id:
            body["investigation_id"] = investigation_id
        if record.exc_text:
            body["exception"] = record.exc_text

        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                body[key] = value

        # `default=str` rather than raising: a log call must not fail because
        # someone attached an object json cannot serialise. Losing the type is
        # better than losing the line.
        return json.dumps(body, default=str)


def configure(level: int = logging.INFO, *, secrets: list[str] | None = None) -> None:
    """Install the formatter and the redacting filter on the root logger.

    Idempotent: calling it twice does not stack two handlers, which would print
    every line twice and redact it twice - the second pass being harmless and
    the duplicate output not.
    """
    root = logging.getLogger()
    root.setLevel(level)

    for existing in list(root.handlers):
        if getattr(existing, "_pantheon", False):
            root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter(secrets))
    handler._pantheon = True  # type: ignore[attr-defined]
    root.addHandler(handler)
