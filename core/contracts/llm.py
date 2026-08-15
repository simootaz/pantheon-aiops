"""Delphi contracts: what an agent needs, and how Delphi answered.

Agents declare `ModelRequirements` and never name a model. Delphi resolves those
requirements to a concrete `ModelDescriptor` at call time and records the
decision as a `ResolutionRecord`, which travels with the Investigation.

Nothing here ever carries an API key. `ProviderConfig.secret_ref` names a key in
the keyring; the key itself lives only in `core.llm.keyring` and is redacted in
traces. A credential reaching one of these models would be a security bug, since
they are persisted, exported in reports and rendered in the dashboard.

See docs/adr/0004-llm-provider-abstraction.md.

Phase 2 will expand this: streaming chunk contracts and per-provider rate-limit
descriptors.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel


class Capability(StrEnum):
    """A behaviour a model either demonstrably has or does not.

    Membership is established by probing, never by a hardcoded table - see
    core.llm.probe.
    """

    TOOL_USE = "tool_use"
    JSON_MODE = "json_mode"
    VISION = "vision"
    STREAMING = "streaming"


class Tier(StrEnum):
    """Cost/capability band an agent asks for, rather than a specific model."""

    CHEAP = "cheap"
    BALANCED = "balanced"
    FRONTIER = "frontier"


class Dialect(StrEnum):
    """Wire format a provider speaks.

    Named by wire format rather than by vendor: a dialect outlives the vendor
    that popularised it, and several vendors speak each one.

    - CHAT_COMPLETIONS: OpenRouter, Groq, Together, DeepSeek, Mistral, vLLM,
      LM Studio, Ollama, OpenAI and most self-hosted stacks.
    - MESSAGES: Anthropic and API-compatible gateways.
    - GENERATE_CONTENT: Google Gemini.
    - RAW: bespoke HTTP APIs, mapped by configuration.
    """

    CHAT_COMPLETIONS = "chat_completions"
    MESSAGES = "messages"
    GENERATE_CONTENT = "generate_content"
    RAW = "raw"


class AuthMode(StrEnum):
    """How credentials are presented to a provider."""

    NONE = "none"
    BEARER = "bearer"
    HEADER_KEY = "header_key"
    QUERY_PARAM = "query_param"


class ResolutionStep(StrEnum):
    """Which rung of the resolution cascade produced the answer."""

    TASK_OVERRIDE = "task_override"
    AGENT_BINDING = "agent_binding"
    TIER_DEFAULT = "tier_default"
    GLOBAL_DEFAULT = "global_default"


class ModelRequirements(ContractModel):
    """What an agent needs from a model. The only thing an agent may declare."""

    capabilities: list[Capability] = Field(
        default_factory=list, description="Capabilities the model must demonstrably have."
    )
    min_context: int = Field(default=0, ge=0, description="Minimum context window in tokens.")
    tier: Tier = Tier.BALANCED
    max_cost_per_call: float | None = Field(
        default=None,
        ge=0.0,
        description="Ceiling for one call. Enforced via core.guardrails.budget.",
    )


class ProviderConfig(ContractModel):
    """A configured provider. Added from settings, never from code."""

    id: str = Field(description="Stable identifier, e.g. 'local-ollama'.")
    display_name: str
    dialect: Dialect
    base_url: str = Field(description="Root URL of the provider's API.")
    auth_mode: AuthMode = AuthMode.BEARER
    secret_ref: str | None = Field(
        default=None,
        description="Name of the credential in the keyring. Never the credential itself.",
    )
    models_endpoint: str | None = Field(
        default=None, description="Path used to enumerate models, when the provider offers one."
    )
    manual_models: list[str] = Field(
        default_factory=list, description="Model ids entered by hand when enumeration is absent."
    )
    enabled: bool = True


class ModelDescriptor(ContractModel):
    """One model as observed, not as advertised.

    Every field below the identity pair is measured by core.llm.probe against
    this deployment, because a model's behaviour behind a particular gateway is
    not always what its vendor documents.
    """

    provider_id: str
    model_id: str
    context_window: int = Field(default=0, ge=0)
    capabilities: list[Capability] = Field(
        default_factory=list, description="Probed, not declared."
    )
    input_cost_per_1k: float | None = Field(default=None, ge=0.0)
    output_cost_per_1k: float | None = Field(default=None, ge=0.0)
    median_latency_ms: int | None = Field(default=None, ge=0)
    last_probed_at: datetime | None = Field(
        default=None, description="Null means never probed; treat capabilities as unknown."
    )


class ResolutionRecord(ContractModel):
    """Why Delphi chose the model it chose, for one call.

    Attached to the Investigation so a run is reproducible and can explain its
    own cost without being re-run.
    """

    id: UUID
    requested_by: str = Field(description="Agent codename that consulted Delphi, e.g. 'hermes'.")
    requirements: ModelRequirements
    matched_step: ResolutionStep
    chosen: ModelDescriptor
    rejected: list[str] = Field(
        default_factory=list,
        description="Human-readable reason per rejected candidate, in evaluation order.",
    )
    fallback_used: bool = False
    estimated_cost: float | None = Field(default=None, ge=0.0)
    resolved_at: datetime


# TODO: Phase 2 - add streaming chunk contracts and rate-limit descriptors
