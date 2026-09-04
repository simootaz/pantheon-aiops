"""Every path a secret could take into a log line, and the filter that closes it.

`core/cerberus/redaction.py` has been implemented and tested since Phase 0 while
being wired to nothing. Traces and prompts were covered; logs were not, and the
one module using logging calls `logger.exception(...)`, which writes an
exception's message verbatim.

The tests below are one per route in: the message, the format arguments, the
`extra=` payload, and the rendered traceback. A filter covering three of four is
a filter that reads as protection.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any
from uuid import uuid4

import pytest

from core.observability.logging import (
    JsonFormatter,
    RedactingFilter,
    configure,
    configured_secrets,
    investigation,
)

SECRET = "gsk_live_a_key_that_must_not_reach_a_log"


@pytest.fixture(autouse=True)
def _pristine_root() -> Any:
    """Restore the root logger around every test in this file.

    Two tests here install handlers on the ROOT logger, which is process-wide.
    Without this, `test_configure_does_not_stack_handlers` passed alone and
    failed in the full suite - it counted a handler another test had left
    behind. A test that only passes depending on order is the same family as a
    guard with no subject: green for a reason unrelated to its claim.
    """
    root = logging.getLogger()
    original = list(root.handlers)
    yield
    root.handlers[:] = original


@pytest.fixture
def emitted() -> Any:
    """A logger writing JSON into a buffer, filtered exactly as production is."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter([SECRET]))

    logger = logging.getLogger(f"test.{uuid4().hex}")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.propagate = False

    def lines() -> list[dict[str, Any]]:
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    logger.lines = lines  # type: ignore[attr-defined]
    return logger


# --- the four routes in ------------------------------------------------------------


def test_a_secret_in_the_message_is_scrubbed(emitted: Any) -> None:
    emitted.info("connecting with %s", "nothing")
    emitted.info(f"authorization failed for {SECRET}")

    rendered = json.dumps(emitted.lines())
    assert SECRET not in rendered
    assert "[REDACTED]" in rendered


def test_a_secret_in_a_format_argument_is_scrubbed(emitted: Any) -> None:
    """`logger.info("key=%s", key)` is the most natural way to write the leak."""
    emitted.info("calling provider with key=%s", SECRET)

    assert SECRET not in json.dumps(emitted.lines())


def test_a_secret_in_an_extra_payload_is_scrubbed(emitted: Any) -> None:
    """`extra=` is carried into the JSON, so it is a route in like any other."""
    emitted.info("provider configured", extra={"config": {"api_key": SECRET, "base": "u"}})

    line = emitted.lines()[0]
    assert SECRET not in json.dumps(line)
    assert line["config"]["base"] == "u", "redaction destroyed the readable part too"


def test_a_secret_in_a_traceback_is_scrubbed(emitted: Any) -> None:
    """The route that actually exists today.

    `api/routers/alerts.py` calls `logger.exception(...)`, and a provider
    answering `401 for key gsk_...` puts that string in the exception message,
    which lands in the rendered traceback verbatim.
    """
    try:
        raise RuntimeError(f"401 unauthorized for key {SECRET}")
    except RuntimeError:
        emitted.exception("investigation failed")

    rendered = json.dumps(emitted.lines())
    assert SECRET not in rendered
    assert "RuntimeError" in rendered, "the traceback was scrubbed away entirely"


def test_a_pattern_shaped_secret_is_caught_without_being_registered(emitted: Any) -> None:
    """The literal list only covers what is configured. Pattern rules are what
    catch a credential nobody registered - as long as it is shaped like one."""
    emitted.info("state", extra={"payload": {"password": "hunter2-and-then-some"}})

    assert "hunter2" not in json.dumps(emitted.lines())


def test_a_reference_stays_readable(emitted: Any) -> None:
    """Redacting `credential_ref` would blind the audit trail this system
    depends on. The name of a secret is not the secret."""
    emitted.info("leased", extra={"payload": {"credential_ref": "cerberus://groq"}})

    assert "cerberus://groq" in json.dumps(emitted.lines())


# --- correlation --------------------------------------------------------------------


def test_lines_inside_an_investigation_carry_its_id(emitted: Any) -> None:
    identifier = uuid4()

    with investigation(identifier):
        emitted.info("started")
    emitted.info("after")

    inside, outside = emitted.lines()
    assert inside["investigation_id"] == str(identifier)
    assert "investigation_id" not in outside


def test_the_tag_is_removed_even_when_the_block_raises(emitted: Any) -> None:
    """A leaked tag attributes the NEXT investigation's lines to the previous
    one - worse than no correlation, because absent correlation is visibly
    absent and wrong correlation is not."""
    with pytest.raises(RuntimeError), investigation(uuid4()):
        raise RuntimeError("boom")

    emitted.info("after")

    assert "investigation_id" not in emitted.lines()[0]


def test_nested_investigations_restore_the_outer_one(emitted: Any) -> None:
    outer, inner = uuid4(), uuid4()

    with investigation(outer):
        with investigation(inner):
            emitted.info("inner")
        emitted.info("outer again")

    assert [line["investigation_id"] for line in emitted.lines()] == [str(inner), str(outer)]


# --- the filter is on the handler, and configure is idempotent ------------------------


def test_configure_does_not_stack_handlers() -> None:
    """Calling it twice would print every line twice, and the duplicate output
    is the half that is not harmless."""
    root = logging.getLogger()

    configure(secrets=[SECRET])
    once = len([h for h in root.handlers if getattr(h, "_pantheon", False)])
    configure(secrets=[SECRET])
    twice = len([h for h in root.handlers if getattr(h, "_pantheon", False)])

    assert once == 1
    assert twice == 1, f"configuring twice installed {twice} handlers"


def test_an_unserialisable_value_does_not_lose_the_line(emitted: Any) -> None:
    """A log call must not fail because someone attached an object json cannot
    serialise. Losing the type is better than losing the line."""

    class _Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    emitted.info("state", extra={"payload": _Opaque()})

    assert "<opaque>" in json.dumps(emitted.lines())


# --- where the literals come from -------------------------------------------------------


def test_configured_secrets_finds_every_secret_the_settings_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read from settings rather than hand-maintained. A list someone keeps by
    hand goes stale the first time a credential is added, and the failure is
    silent until the day that credential appears in a log."""
    from pydantic import SecretStr

    import core.observability.logging as module
    from core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.delphi, "api_key", SecretStr(SECRET))
    monkeypatch.setattr(module, "configured_secrets", configured_secrets)

    assert SECRET in configured_secrets()


def test_configured_secrets_skips_the_empty_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty SecretStr as a literal would replace every empty string in every
    log line, which destroys the logs without protecting anything."""
    from pydantic import SecretStr

    from core.config import get_settings

    monkeypatch.setattr(get_settings().delphi, "api_key", SecretStr(""))

    assert "" not in configured_secrets()


# --- it is actually installed ---------------------------------------------------------


def test_building_the_app_installs_the_redacting_filter() -> None:
    """A filter nothing installs is a filter that reads as protection.

    Configured during `create_app`, before anything can log: a handler installed
    later would let every line emitted during construction out unredacted, and
    construction is exactly where a misconfigured credential gets mentioned.
    """
    from api.main import create_app
    from core.store.investigations import InMemoryInvestigationStore
    from core.store.providers import InMemoryProviderStore

    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not getattr(h, "_pantheon", False)]

    create_app(
        investigation_store=InMemoryInvestigationStore(),
        provider_store=InMemoryProviderStore(master=b"0" * 32),
    )

    installed = [h for h in root.handlers if getattr(h, "_pantheon", False)]
    assert installed, "create_app did not configure logging"
    assert any(isinstance(f, RedactingFilter) for f in installed[0].filters), (
        "the handler is installed without the redacting filter, so every line "
        "reaches the log unscrubbed"
    )
