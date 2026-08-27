"""Prompt/response tracing, token accounting and cost attribution.

Emits a span per model call carrying the resolved model, token counts and
measured cost, so an Investigation can explain what it spent and where.

Credentials are redacted here before anything is emitted, using
core.cerberus.redaction. Provider keys must never reach a log line, a span
attribute or a ResolutionRecord.

WHY THE PROMPT IS NOT IN THE SPAN BY DEFAULT
----------------------------------------------
A prompt assembled from an Investigation carries whatever the connectors
returned - pod names, log lines, occasionally a stack trace with a token in it.
Redaction removes the secrets Cerberus knows about, and cannot remove the ones
nobody registered.

So the span carries a *length* and a *hash*, not the text. The hash is enough to
tell two runs apart and to confirm a prompt was identical across a retry, which
is what the span is actually asked. Anyone who needs the text can turn it on
deliberately with `include_prompt=True` and own that decision.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.cerberus.redaction import redact
from core.contracts.llm import ModelDescriptor, ResolutionStep


@dataclass
class ModelCallSpan:
    """One consultation, as it will be read after the fact."""

    requested_by: str
    provider_id: str
    model_id: str
    matched_step: ResolutionStep
    prompt_chars: int
    prompt_digest: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None
    duration_ms: int = 0
    failed: bool = False
    error: str = ""
    fallback_used: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Present only when a caller asked for it, and redacted when it is.
    prompt: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def digest(prompt: str) -> str:
    """A short, stable fingerprint of a prompt.

    Enough to tell two runs apart and to confirm a retry sent the same thing.
    Not reversible, which is the point - see the module docstring.
    """
    return hashlib.blake2b(prompt.encode("utf-8"), digest_size=8).hexdigest()


def span_for(
    *,
    requested_by: str,
    model: ModelDescriptor,
    matched_step: ResolutionStep,
    prompt: str,
    fallback_used: bool = False,
    include_prompt: bool = False,
    secrets: list[str] | None = None,
) -> ModelCallSpan:
    """Open a span for one call.

    `include_prompt` is off by default and redacted when on. Redaction removes
    what Cerberus knows about; it cannot remove a credential nobody registered,
    which is why the default is to carry a digest instead of the text.
    """
    return ModelCallSpan(
        requested_by=requested_by,
        provider_id=model.provider_id,
        model_id=model.model_id,
        matched_step=matched_step,
        prompt_chars=len(prompt),
        prompt_digest=digest(prompt),
        fallback_used=fallback_used,
        prompt=str(redact(prompt, secrets)) if include_prompt else None,
    )
