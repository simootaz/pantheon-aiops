# ADR 0005 — Cerberus: credential brokering

- **Status:** Accepted
- **Date:** 2026-08-15
- **Decided on branch:** `feature/cerberus-credential-brokering`
- **Implementation:** Phase 3. Settings surface: Phase 4.

## Context

Pantheon investigates real systems, so it needs real credentials: database
logins, SSH keys, kubeconfigs, HTTP auth, cloud keys, TLS material, and
arbitrary key-value secrets — each scoped to a server, a service, an
environment. Agents need to reach those systems.

The obvious implementation is to give the agent the credential. That
implementation is unacceptable, and the reason is specific rather than general
caution.

**An agent is an LLM.** A secret placed in an agent's context becomes part of a
prompt. That prompt is sent to a model provider and logged — by us, by the
provider, and by anything in between. The moment a credential enters a prompt it
has left the building: it is in a third party's storage, we cannot audit who
read it, and we cannot revoke it from their logs. It is an **unauditable,
unrevocable exfiltration path**, and it opens on the ordinary success path, not
on an error.

The threat model is therefore not "an agent might be careless". It is:

> **Assume the agent is fully prompt-injected and actively hostile.** It must be
> unable to leak what it was never given.

That framing rules out every design where the agent holds the secret, including
short-lived credentials and one-time tokens: a hostile agent exfiltrates a
30-second credential in well under 30 seconds.

## Decision

**Cerberus is the credential broker.** Three heads: **store** (custody),
**policy** (decisions), **audit** (memory).

Cerberus is infrastructure beside the orchestrator, like Delphi. It is **not an
agent**: no roster entry, no `manifest.yaml`, never dispatched by Zeus.

### The central invariant

> **Agents never receive credential plaintext.**

```python
# FORBIDDEN — the secret is now in the agent's context, and therefore in a prompt
password = cerberus.get_secret("prod-postgres")
rows = connector.query(f"SELECT ...", password=password)

# The only sanctioned shape — the agent asks for a capability, not a secret
lease = cerberus.request_access(
    AccessRequest(
        credential_ref=prod_postgres,
        action=CredentialAction.READ,
        reason="Testing whether the 5xx spike correlates with connection-pool exhaustion",
        requested_ttl_seconds=300,
    )
)
rows = connector.query("SELECT count(*) FROM pg_stat_activity", lease=lease)
```

The agent receives **rows**. It never holds, and cannot obtain, the password.

### The brokering flow

```
agent: "I need prod-postgres, read, because <hypothesis>"
   │
   ▼
policy: is there a grant? (agent, target, action, scope, ttl)
   │
   ├── no grant ──► Approval Gate ──► human decides ──► grant
   │
   ▼
lease: minted, bound to ONE connector and ONE investigation, short TTL
   │
   ▼
connector: redeems the lease for plaintext, executes, returns results
   │
   ▼
agent: receives RESULTS ONLY
```

Every step writes to the audit log.

## Contract surface

Seven types in `core/contracts/credentials.py`, flowing through codegen
([ADR 0002](0002-codegen-from-json-schema.md)) to Go and TypeScript:

| Type | Role |
|---|---|
| `CredentialType` | database, ssh, kubeconfig, http_auth, cloud_key, tls, key_value |
| `CredentialRef` | identifies a credential — **never the value** |
| `PermissionMode` | Deny · Ask each time · Allow for this investigation · Allow until *date* |
| `Grant` | standing permission: agent, credential, action, mode, scope, expiry |
| `Lease` | redeemable permission, bound to one connector and one investigation |
| `AccessRequest` | the ask, carrying the agent's stated reason |
| `AuditEntry` | one immutable line of what happened |

**There is deliberately no `CredentialValue`.** Plaintext has *no contract
representation at all*. It is produced only by `core.cerberus.redemption` and
returned through a path that never touches `core.contracts`, so it cannot be
serialised, persisted, streamed over the WebSocket, or rendered.

Note that fields are named `credential_ref`, not `credential`. The name states
the invariant at every call site.

## Permission modes and defaults

| Mode | Meaning |
|---|---|
| `DENY` | Never, without asking |
| `ASK_EACH_TIME` | Approval Gate on every request |
| `ALLOW_FOR_INVESTIGATION` | Standing for this run; expires with it |
| `ALLOW_UNTIL` | Standing until a date |

**Read and write are separate grants.** Approving read never implies write,
mirroring the connector split between `internal/readonly/` and `internal/write/`.

**Production targets and all write actions default to `ASK_EACH_TIME`** and
cannot be set to `ALLOW_UNTIL` without an explicit override flag on the grant.
The default is the security posture: anyone may widen it deliberately, nobody
should widen it by accident.

`ALLOW_FOR_INVESTIGATION` expires with the run that requested it, so a broad
approval cannot outlive the reason it was given.

## Approval UX reuses the Approval Gate

Credential approvals flow through the **existing** `core/guardrails/
approval_gate.py`. **We do not build a second inbox.** An operator with two
approval queues will learn to skim both.

Every request carries: the agent's **stated reason**, the **exact scope**, the
**lease TTL**, and the **investigation id**.

> Approving *"an agent wants database access"* is not a decision. Approving
> *"Argus wants read on prod-postgres for 5 minutes to test whether the 5xx
> spike correlates with connection-pool exhaustion"* is a real one.

Without the reason, the approval is a rubber stamp with extra steps.

## Lease expiry mid-investigation

A lease **auto-renews** while its underlying grant is still valid and the
investigation is still running.

If the grant has expired or been revoked, renewal **fails**, and the agent
receives a typed `LeaseExpired` failure that it **must surface as a Finding —
never swallow**. The investigation then completes with a **partial result**,
explicitly marked, rather than dying or silently skipping the check.

This is the important half. An investigation that quietly drops a check produces
a verdict that looks complete and is not, which is worse than an obvious
failure: the operator acts on a conclusion whose evidence was never gathered.

## Revocation and rotation

**Rotation** (`store/rotation.py`) rotates a credential in place and **retains
the previous version** until the last lease issued against it expires. Without
retention, rotating during an incident breaks the investigation diagnosing that
incident — precisely when rotation is most likely.

**Revocation** (`policy/revocation.py`) has three scopes:

1. revoke one grant,
2. revoke every grant held by one agent,
3. **break-glass** — revoke everything and invalidate every live lease
   immediately.

Break-glass is the 3am control. When an agent is misbehaving there is no time to
reason about which grant matters; the only useful action is to stop all of them
at once. **Live leases must die with the grants**, or revocation is merely
advisory for as long as the longest outstanding TTL.

## Audit

Every request, grant, denial, lease mint, lease use, renewal, expiry, revocation
and rotation is appended to an **immutable** log and attached to the
Investigation.

Append-only is the point: an audit trail that can be edited answers nothing. A
run must be answerable — after the fact, to someone who was not there — for what
it touched and why.

`AuditEntry` is attached to the `Investigation`, which agents can see. That is
safe **because** every credential in it is a `CredentialRef`, and the schema
scan described below is what keeps that true.

## Encryption

**Envelope encryption**: a per-credential data key, wrapped by a master key.
Rotating the master key rewraps data keys rather than re-encrypting every
credential.

The master key resolves from environment, Sealed Secret, or an external KMS. It
is **never written to disk in plaintext** and **never included unencrypted in a
backup** — a constraint `deploy/backup/` inherits from
[ADR 0001](0001-object-storage-minio.md), since backups land in object storage.

## Enforcement

Three independent guards in `tests/unit/test_credential_safety.py`, each
catching what the others cannot.

**1. Contract surface, in every language.** The generated JSON Schema, Go and
TypeScript artifacts are scanned for any property that could hold a secret
(`password`, `token`, `secret`, `private_key`, …), allowing only reference forms
(`*_ref`, `*_id`, `*_name`, …). Running it on the *generated* output is the
point: the invariant must hold in Go and TypeScript too, and for models added
later by someone who never read this ADR.

The heuristic is itself pinned by a test, in both directions, so exemptions
cannot creep in. One exemption exists today — LLM token *counts* (`max_tokens`)
are a homograph, held as a short explicit list rather than a cleverer regex so
every exemption stays visible.

**2. Import graph.** Nothing under `agents/` may import
`core.cerberus.redemption` or `core.cerberus.store`. Agents may import **only**
`core.cerberus.broker` and `core.cerberus.redaction`; the allowed surface is
documented in `core/cerberus/__init__.py` and asserted by test.

A contract check alone would miss this: an agent that imported the store
directly would never need to *serialise* a secret to leak it — it would simply
have it in context, which is the exact failure being prevented.

**3. Redaction.** `core/cerberus/redaction.py` is **implemented, not stubbed** —
a stubbed redactor cannot be tested, and an untested redactor is worse than
none, because it creates the belief that scrubbing is happening. A test plants a
known secret and asserts it survives **none** of the three sinks: a log line, a
trace attribute mapping, and a prompt.

Redaction is the last line of defence, not the first. The first is never giving
the agent the secret.

**Guards 1 and 3 cover different halves and neither is redundant.** The schema
scan reads *field names*: it catches a contract that declares somewhere to put a
secret. Redaction reads *values*: it catches a secret pasted into a field whose
name is entirely innocent — a log line, a prompt, an A2UI `Text` body. A contract
can pass the scan and still carry a secret, so dropping either leaves a real half
of the threat uncovered.

The same pair covers agent-authored UI, which is a sink in exactly this sense —
see [ADR 0006](0006-agentic-ui-protocols.md).

## Consequence for Delphi

**`core/llm/keyring.py` is deleted.** Provider API keys are just another
credential type. One vault, one audit log, one rotation path, one break-glass.

A second secret store would mean two rotation procedures, two audit trails, and
an even chance of an engineer reaching for the wrong one.
[ADR 0004](0004-llm-provider-abstraction.md) is amended accordingly, and no
re-export shim was left behind — a shim would leave two apparent secret stores
in the tree, which is the problem it purports to solve.

## Consequences

**Good**

- A fully prompt-injected agent cannot leak a credential it never held.
- One audit trail answers "what did this run touch, and who approved it".
- Rotation and break-glass exist as first-class operations rather than
  emergencies improvised at 3am.
- Approvals are decisions about hypotheses, not about vague access.

**Costs**

- A broker sits on every credential path; connectors must redeem leases rather
  than read config.
- Lease renewal is machinery that must work, and its failure mode must be a
  visible partial result.
- Old-version retention means a rotated credential remains valid briefly.
- Break-glass is destructive by design: it will interrupt legitimate
  investigations, which is the correct trade at the moment it is used.

## Alternatives considered

| Option | Why not |
|---|---|
| **Env vars injected into agent processes** | The secret is in the process, hence in context, hence in prompts. Exactly the path being closed. |
| **Short-lived credentials handed to agents** | A hostile agent exfiltrates a 30-second credential in far less than 30 seconds. Shortening the window does not change the property. |
| **Per-connector secret configuration** | Works, but has no per-agent policy, no approval flow, no audit and no revocation. It answers "can this connector connect", not "should this agent, now, for this reason". |
| **Reuse the Kubernetes secret store directly** | Only covers in-cluster targets, offers no per-agent grants, and no shared audit trail. |

## Phase plan

| Phase | Delivers |
|---|---|
| **0** | Structure, contracts, `redaction.py` implemented, all three guards |
| **3** | store, policy, audit, broker, lease, redemption; Approval Gate integration |
| **4** | Settings surface: credential inventory, grant table, permission modes, audit viewer |
| **5** | Rotation scheduling and break-glass runbook |
