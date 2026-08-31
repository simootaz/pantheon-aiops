"""The only module in Pantheon that reads the environment.

WHY THIS EXISTS
---------------
Before this, `os.environ.get("PROMETHEUS_URL", "http://localhost:9090")` appeared
wherever it was needed. Every one of those is two failures waiting:

* **dev and prod diverge silently.** One call site gets a new variable, another
  keeps the old default, and nothing says so.
* **a typo falls back.** `os.environ.get("PROMETEUS_URL", "http://localhost:9090")`
  returns a working-looking default forever. Nothing is missing, nothing errors,
  and the service quietly talks to the wrong Prometheus, or to none.

So configuration is read **once**, here, into typed models.
`tests/unit/test_centralized_config.py` fails the build if any other module
touches `os.environ`.

SHAPE
-----
One group per subsystem, so call sites read `settings.prometheus.url` rather
than picking one of forty flat names::

    from core.config import get_settings

    settings = get_settings()
    httpx.get(f"{settings.prometheus.base}/api/v1/query")

Each group carries an `env_prefix`, so the environment variable names stay
exactly what `.env.example`, Compose, Helm and the Go modules already use.
Nothing is renamed by being centralised.

DEFAULTS POLICY
---------------
* **URLs and tunables** get dev-shaped defaults, so `make up` works with no
  `.env` at all.
* **Secrets get no default.** They are `SecretStr | None`, empty locally, and
  `PANTHEON_ENV=production` makes their absence a startup failure rather than a
  silent fallback. This mirrors the Helm chart's `productionMode`, which fails
  closed on the same set.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.contracts.llm import AuthMode, Dialect, Tier

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"


class Environment(StrEnum):
    """Where this process thinks it is running."""

    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


#: `Dialect`, `AuthMode` and `Tier` come from `core/contracts/llm.py`, not from
#: here.
#:
#: They were defined in both, with identical members. Nothing had gone wrong yet,
#: which is the only reason it survived: two definitions of one closed vocabulary
#: agree until someone adds a member to one of them, and then a setting parses
#: into an enum the contract cannot represent. mypy caught it the first time a
#: module used both - `core.config.Dialect` is not `core.contracts.llm.Dialect`,
#: however identical they look.
#:
#: The contract is the source, because it is the one that reaches Go and
#: TypeScript through codegen. A settings module that redefined it would be
#: publishing a second vocabulary no generator sees.


def _group(prefix: str) -> SettingsConfigDict:
    """Config shared by every group: its prefix, and the same .env file."""
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


def _base(url: HttpUrl) -> str:
    """A URL without its trailing slash.

    `str(HttpUrl("http://x:9090"))` is `"http://x:9090/"`, so joining a path onto
    it produces a double slash. Every caller wants the base, so it is offered
    once here rather than rstripped at forty call sites.
    """
    return str(url).rstrip("/")


class ApiSettings(BaseSettings):
    """The HTTP surface this process serves."""

    model_config = _group("PANTHEON_API_")

    # nosec B104 - binding every interface is the point in a container; the
    # network boundary is the container, not the bind address. Suppressed here
    # rather than repo-wide so a real 0.0.0.0 bind elsewhere still trips.
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8000, ge=1, le=65535)

    #: `subject:role,role=token;subject:role=token`. Parsed by
    #: `api/auth/dependencies.py`, which refuses a malformed entry rather than
    #: skipping it - an ignored entry silently reduces the set of people who can
    #: approve, and the symptom reads as one person's problem.
    #:
    #: Empty authenticates nobody. It does NOT authenticate everybody, which is
    #: the bug this shape invites: an empty credential matching an unset
    #: expectation. Production refuses to start without one.
    tokens: SecretStr | None = None


class PrometheusSettings(BaseSettings):
    model_config = _group("PROMETHEUS_")

    url: HttpUrl = HttpUrl("http://localhost:9090")

    @property
    def base(self) -> str:
        return _base(self.url)


class LokiSettings(BaseSettings):
    model_config = _group("LOKI_")

    url: HttpUrl = HttpUrl("http://localhost:3100")

    #: The LogQL selector Lethe reads. Deliberately NOT the simulator's
    #: `LOKI_JOB_LABEL`, which is what the simulator writes: one is a producer's
    #: identity and one is a consumer's scope, they belong to different systems,
    #: and in any real deployment they differ. The dev-shaped default happens to
    #: match because the only producer here today is the simulator.
    #:
    #: One selector for both the incident and the reference window - narrowing it
    #: per window would make them disagree about what "the logs" are.
    selector: str = '{job="pantheon-sim"}'

    @property
    def base(self) -> str:
        return _base(self.url)


class PushgatewaySettings(BaseSettings):
    model_config = _group("PUSHGATEWAY_")

    url: HttpUrl = HttpUrl("http://localhost:9091")

    @property
    def base(self) -> str:
        return _base(self.url)

    @property
    def host_port(self) -> str:
        """`host:port`, which is what the prometheus_client pusher expects."""
        return _base(self.url).split("://", 1)[-1]


class AlertmanagerSettings(BaseSettings):
    model_config = _group("ALERTMANAGER_")

    url: HttpUrl = HttpUrl("http://localhost:9093")
    #: Shared secret for POST /webhooks/alertmanager. Empty disables
    #: verification, which is fine locally and is not fine anywhere a real
    #: Alertmanager can reach.
    webhook_token: SecretStr | None = None

    @property
    def base(self) -> str:
        return _base(self.url)


class PostgresSettings(BaseSettings):
    model_config = _group("POSTGRES_")

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    db: str = "pantheon"
    user: str = "pantheon"
    password: SecretStr | None = None


class RedisSettings(BaseSettings):
    model_config = _group("REDIS_")

    url: str = "redis://localhost:6379/0"


class ObjectStorageSettings(BaseSettings):
    """S3-compatible. MinIO by default; any endpoint must work (ADR 0001)."""

    model_config = _group("S3_")

    endpoint_url: HttpUrl = HttpUrl("http://minio:9000")
    access_key: str = "pantheon"
    secret_key: SecretStr | None = None
    region: str = "us-east-1"
    bucket_reports: str = "pantheon-reports"
    bucket_artifacts: str = "pantheon-artifacts"
    bucket_backups: str = "pantheon-backups"
    use_ssl: bool = False

    @property
    def base(self) -> str:
        return _base(self.endpoint_url)


class DelphiSettings(BaseSettings):
    """The LLM gateway. Agents declare requirements; they never name a model."""

    model_config = _group("LLM_")

    provider_id: str = "local-ollama"
    display_name: str = "Local Ollama"
    dialect: Dialect = Dialect.CHAT_COMPLETIONS
    base_url: HttpUrl = HttpUrl("http://ollama:11434/v1")
    auth_mode: AuthMode = AuthMode.NONE
    api_key: SecretStr | None = None

    tier_cheap_model: str = "qwen2.5:3b"
    tier_balanced_model: str = "qwen2.5:14b"
    tier_frontier_model: str = "qwen2.5:32b"
    global_default_tier: Tier = Tier.BALANCED

    max_tokens: int = Field(default=8192, gt=0)
    request_timeout_seconds: int = Field(default=120, gt=0)
    max_cost_per_call: float | None = Field(default=None, ge=0.0)

    @property
    def base(self) -> str:
        return _base(self.base_url)

    @model_validator(mode="after")
    def _auth_mode_implies_a_key(self) -> DelphiSettings:
        """A provider asking for a credential must have been given one."""
        if self.auth_mode is not AuthMode.NONE and self.api_key is None:
            raise ValueError(
                f"LLM_AUTH_MODE={self.auth_mode.value} needs LLM_API_KEY. "
                "Set it, or use LLM_AUTH_MODE=none for a local provider."
            )
        return self


class CerberusSettings(BaseSettings):
    """The credential broker. Agents never receive plaintext (ADR 0005)."""

    model_config = _group("CERBERUS_")

    master_key: SecretStr | None = None
    lease_seconds: int = Field(default=900, gt=0)
    audit_retention_days: int = Field(default=90, gt=0)


class TemporalSettings(BaseSettings):
    model_config = _group("TEMPORAL_")

    host: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "pantheon"


class GitLabSettings(BaseSettings):
    model_config = _group("GITLAB_")

    url: HttpUrl = HttpUrl("https://gitlab.com")
    token: SecretStr | None = None
    webhook_token: SecretStr | None = None

    @property
    def base(self) -> str:
        return _base(self.url)


class GitHubSettings(BaseSettings):
    model_config = _group("GITHUB_")

    #: github.com by default, and a setting rather than a constant so GitHub
    #: Enterprise is reachable by configuration rather than by an edit. An
    #: endpoint hardcoded in a connector is one that cannot be pointed anywhere
    #: else without a release.
    api_url: HttpUrl = HttpUrl("https://api.github.com")
    token: SecretStr | None = None

    @property
    def base(self) -> str:
        return _base(self.api_url)


class KubernetesSettings(BaseSettings):
    """No prefix: KUBECONFIG is a well-known name owned by kubectl, not by us."""

    model_config = _group("")

    kubeconfig: str = ""


class LitmusSettings(BaseSettings):
    model_config = _group("LITMUS_")

    url: str = ""


class ObservabilitySettings(BaseSettings):
    model_config = _group("OTEL_")

    exporter_otlp_endpoint: HttpUrl = HttpUrl("http://localhost:4317")
    service_name: str = "pantheon"


class SimulatorSettings(BaseSettings):
    """Where the simulator writes, and how fast it claims to run by default."""

    model_config = _group("SIM_")

    webhook_url: HttpUrl = HttpUrl("http://localhost:8000/webhooks/gitlab")
    default_speed: float = Field(default=500.0, gt=0.0)

    @property
    def webhook(self) -> str:
        return _base(self.webhook_url)


#: Secrets deliberately allowed to be absent in production, and why. Every
#: SecretStr field must appear here or in REQUIRED_IN_PRODUCTION - a guard
#: enforces the partition, so adding a credential forces a decision instead of
#: letting it default to unguarded.
#:
#: This exists because CONTRIBUTING claimed "a guard checks each" of the three
#: steps for adding a setting, and the third step had no guard at all. Four
#: SecretStr fields had quietly fallen outside the required set, including one
#: added in the same session that wrote the claim.
OPTIONAL_IN_PRODUCTION: dict[str, str] = {
    "GITHUB_TOKEN": "only needed by the GitHub connector; a Prometheus-only "
    "deployment must not be forced to invent one",
    "GITLAB_TOKEN": "same - the GitLab connector is optional. Note the webhook "
    "token IS required: that one guards an inbound endpoint",
    "LLM_API_KEY": "a local provider needs none. DelphiSettings already refuses "
    "an auth_mode that wants a key without one, which is the tighter check",
    "ALERTMANAGER_WEBHOOK_TOKEN": "empty disables verification, which is right "
    "for a cluster where only Alertmanager can reach the endpoint. Unlike the "
    "GitLab hook, this one is not reachable from the public internet",
}

#: Secrets that must be present when PANTHEON_ENV=production, and the variable
#: an operator has to set. Mirrors the Helm chart's productionMode checks.
REQUIRED_IN_PRODUCTION: tuple[tuple[str, str, str], ...] = (
    ("postgres", "password", "POSTGRES_PASSWORD"),
    ("object_storage", "secret_key", "S3_SECRET_KEY"),
    ("cerberus", "master_key", "CERBERUS_MASTER_KEY"),
    ("gitlab", "webhook_token", "GITLAB_WEBHOOK_TOKEN"),
    # Unset means no principal can authenticate, so every gated endpoint is a
    # 401 and the approvals queue is unanswerable. Refused here rather than
    # discovered when somebody tries to approve something at 03:00.
    #
    # Not the same check as `api/auth/dependencies.py`, which refuses an empty
    # TABLE. `PANTHEON_API_TOKENS=";;"` is not None and parses to no
    # principals, and only that one catches it.
    ("api", "tokens", "PANTHEON_API_TOKENS"),
)


class Settings(BaseSettings):
    """Every knob Pantheon has, grouped by the subsystem that owns it."""

    model_config = _group("PANTHEON_")

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"

    api: ApiSettings = Field(default_factory=ApiSettings)
    prometheus: PrometheusSettings = Field(default_factory=PrometheusSettings)
    loki: LokiSettings = Field(default_factory=LokiSettings)
    pushgateway: PushgatewaySettings = Field(default_factory=PushgatewaySettings)
    alertmanager: AlertmanagerSettings = Field(default_factory=AlertmanagerSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    object_storage: ObjectStorageSettings = Field(default_factory=ObjectStorageSettings)
    delphi: DelphiSettings = Field(default_factory=DelphiSettings)
    cerberus: CerberusSettings = Field(default_factory=CerberusSettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    gitlab: GitLabSettings = Field(default_factory=GitLabSettings)
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    kubernetes: KubernetesSettings = Field(default_factory=KubernetesSettings)
    litmus: LitmusSettings = Field(default_factory=LitmusSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    simulator: SimulatorSettings = Field(default_factory=SimulatorSettings)

    @model_validator(mode="after")
    def _secrets_are_present_in_production(self) -> Settings:
        """Fail closed rather than run production on a development default.

        Empty is fine locally: `make up` must work with no .env at all. It is not
        fine anywhere real, and the difference has to be enforced somewhere that
        cannot be skipped, which is here rather than in a runbook.
        """
        if self.env is not Environment.PRODUCTION:
            return self

        missing = [
            variable
            for group, field, variable in REQUIRED_IN_PRODUCTION
            if getattr(getattr(self, group), field) is None
        ]
        if missing:
            raise ValueError(
                f"PANTHEON_ENV=production but these are unset: {', '.join(missing)}. "
                "Production refuses to start on a development default."
            )
        return self


def require_stack() -> bool:
    """Whether a missing observability stack should fail rather than skip.

    `make test-sim` sets PANTHEON_REQUIRE_STACK, because a skipped gate is
    reported as a pass and that gate exists to assert on real data. A bare
    `pytest` on a laptop still skips.

    It lives here rather than in the test because reading the environment
    anywhere else is exactly what this module exists to prevent - including
    from tests, where a typo would silently turn the failure back into a skip.
    """
    return bool(os.environ.get("PANTHEON_REQUIRE_STACK"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read once.

    Cached so that importing configuration is free and so every caller sees the
    same values. `get_settings.cache_clear()` exists for tests that need to
    re-read a changed environment.
    """
    return Settings()
