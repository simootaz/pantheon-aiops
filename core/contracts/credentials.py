"""Cerberus contracts: references to credentials, never credentials.

Every model here is deliberately incapable of carrying a secret. There is no
`CredentialValue` type, and adding one would be a design error rather than a
missing feature: plaintext has **no contract representation at all**. It is
returned by `core.cerberus.redemption` through a path that never touches
`core.contracts`, so it cannot be serialised, persisted, streamed to the
dashboard, or reach an agent.

`CredentialRef` is the name of the invariant. It identifies a credential so a
grant, a lease and an audit entry can talk about one - while being useless to
anyone who obtains it.

`tests/unit/test_credential_safety.py` scans the *generated* JSON Schema, Go and
TypeScript artifacts for any property that could hold a secret. That test is what
keeps this true in every language, including for models added later.

See docs/adr/0005-credential-brokering.md.

Phase 3 will expand this: per-type connection descriptors and rotation history.

Phase: 3 - Guardrails, Approvals & Write Actions
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from core.contracts.base import ContractModel


class CredentialType(StrEnum):
    """What kind of credential this is. Governs how the store handles it."""

    DATABASE = "database"
    SSH = "ssh"
    KUBECONFIG = "kubeconfig"
    HTTP_AUTH = "http_auth"
    CLOUD_KEY = "cloud_key"
    TLS = "tls"
    KEY_VALUE = "key_value"


class CredentialAction(StrEnum):
    """Read and write are separate grants.

    Approving read never implies write, mirroring the connector split between
    internal/readonly and internal/write.

    NOT_APPLICABLE exists for audit entries that concern no single access -
    break-glass and rotation, for instance. It is meaningful only on AuditEntry;
    a Grant, Lease or AccessRequest carrying it is invalid, and Phase 3
    validation rejects it.

    It is also why AuditEntry.action is not simply nullable: a nullable enum
    emits `anyOf: [$ref, null]`, which go-jsonschema v0.24.1 turns into two
    conflicting UnmarshalJSON methods on the same Go type. Stating "not
    applicable" explicitly is clearer than an implicit null convention anyway.
    """

    READ = "read"
    WRITE = "write"
    NOT_APPLICABLE = "not_applicable"


class PermissionMode(StrEnum):
    """How a grant answers a request.

    ALLOW_UNTIL is refused for production targets and for any write action
    unless an explicit override is set - see core.cerberus.policy.defaults.
    """

    DENY = "deny"
    ASK_EACH_TIME = "ask_each_time"
    ALLOW_FOR_INVESTIGATION = "allow_for_investigation"
    ALLOW_UNTIL = "allow_until"


class CredentialScope(ContractModel):
    """Where a credential applies: a server, a service, an environment."""

    server: str | None = Field(default=None, description="Host or cluster, e.g. 'db-01'.")
    service: str | None = Field(default=None, description="Logical service, e.g. 'checkout'.")
    environment: str | None = Field(default=None, description="e.g. 'prod'. Drives defaults.")


class CredentialRef(ContractModel):
    """A reference to a stored credential. Never the credential.

    Safe to persist, to attach to an Investigation and to render in the
    dashboard, because it identifies without disclosing.
    """

    id: str = Field(description="Opaque identifier of the stored credential.")
    name: str = Field(description="Human-readable label, e.g. 'prod-postgres'.")
    type: CredentialType
    scope: CredentialScope = Field(default_factory=CredentialScope)


class Grant(ContractModel):
    """Standing permission for one agent to reach one credential one way."""

    id: UUID
    agent: str = Field(description="Agent codename the grant applies to, e.g. 'argus'.")
    credential_ref: CredentialRef
    action: CredentialAction
    mode: PermissionMode
    investigation_id: UUID | None = Field(
        default=None, description="Set when mode is ALLOW_FOR_INVESTIGATION."
    )
    expires_at: datetime | None = Field(default=None, description="Set when mode is ALLOW_UNTIL.")
    granted_by: str = Field(description="Who approved it.")
    granted_at: datetime
    override_ask_default: bool = Field(
        default=False,
        description="Explicit override allowing ALLOW_UNTIL on a production or write grant.",
    )
    revoked_at: datetime | None = Field(default=None, description="Set when revoked.")


class AccessRequest(ContractModel):
    """An agent asking for a capability, with the reason it is asking.

    `reason` is not decoration. Approving "an agent wants database access" is
    not a decision; approving a stated hypothesis is.
    """

    id: UUID
    investigation_id: UUID
    agent: str
    credential_ref: CredentialRef
    action: CredentialAction
    reason: str = Field(
        description="The hypothesis this access would test, in the agent's own words."
    )
    requested_ttl_seconds: int = Field(gt=0, description="How long the agent expects to need it.")
    requested_at: datetime


class Lease(ContractModel):
    """Permission to use a credential, bound to one connector and one run.

    A lease is not a credential. It is redeemable only by the named connector,
    only for the named investigation, and only until it expires - so a leaked
    lease is worthless anywhere else.
    """

    id: UUID
    request_id: UUID
    investigation_id: UUID
    connector: str = Field(description="The only connector that may redeem this lease.")
    credential_ref: CredentialRef
    action: CredentialAction
    issued_at: datetime
    expires_at: datetime
    renewable: bool = Field(
        default=True,
        description="Auto-renews while the underlying grant is valid and the run is live.",
    )
    renewed_count: int = Field(default=0, ge=0)


class AuditEvent(StrEnum):
    """Everything Cerberus records. The log is append-only."""

    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    APPROVAL_REQUESTED = "approval_requested"
    LEASE_MINTED = "lease_minted"
    LEASE_USED = "lease_used"
    LEASE_RENEWED = "lease_renewed"
    LEASE_EXPIRED = "lease_expired"
    LEASE_REVOKED = "lease_revoked"
    GRANT_REVOKED = "grant_revoked"
    BREAK_GLASS = "break_glass"
    ROTATED = "rotated"


class AuditEntry(ContractModel):
    """One immutable line in the credential audit log.

    Attached to the Investigation, which agents can see - safe because every
    reference here is a CredentialRef and never a value.
    """

    id: UUID
    at: datetime
    event: AuditEvent
    actor: str = Field(description="Agent codename, user, or 'system'.")
    investigation_id: UUID | None = None
    credential_ref: CredentialRef | None = None
    action: CredentialAction = Field(
        default=CredentialAction.NOT_APPLICABLE,
        description="NOT_APPLICABLE for events that concern no single access.",
    )
    lease_id: UUID | None = None
    detail: str = Field(default="", description="Human-readable context. Never a credential.")


# TODO: Phase 3 - add per-type connection descriptors and rotation history
