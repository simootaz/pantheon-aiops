# Architecture Decision Records

Decisions that shaped Pantheon, with the reasoning that produced them. Each ADR
states what was decided, why, what it costs, and what was rejected.

Read the one you need; you should not have to open all seven to find a decision.

| # | Decision | In one line |
|---|---|---|
| [0001](0001-object-storage-minio.md) | **Object storage is MinIO** | S3-compatible interface only, so the stack runs fully self-hosted with no cloud account — and any S3 provider can replace it through config alone. |
| [0002](0002-codegen-from-json-schema.md) | **Codegen reads JSON Schema, never OpenAPI** | Go and TypeScript are generated from one artifact, so there is one drift surface and `verify.sh` guards one pipeline rather than two that can diverge while both look green. |
| [0003](0003-neutral-repository-documentation.md) | **The repository claims no AI authorship** | Attribution patterns are banned; vendor names, model ids and provider docs are explicitly allowed, because those are product content. Includes the history-rewrite addendum. |
| [0004](0004-llm-provider-abstraction.md) | **Delphi — the LLM gateway** | Agents declare `ModelRequirements` and never name a model. Capabilities are **probed**, never tabulated, because a model table is stale within weeks. |
| [0005](0005-credential-brokering.md) | **Cerberus — credential brokering** | Agents never receive plaintext. A secret in an agent's context enters a prompt, which is an unauditable, unrevocable exfiltration path. Credentials are brokered by lease. |
| [0006](0006-agentic-ui-protocols.md) | **AG-UI transport, A2UI payload** | AG-UI is the pipes; A2UI is what travels through them when an agent wants to render something. Agent-generated UI is untrusted **data**, never code. |
| [0007](0007-deferred-actions.md) | **Chronos — deferred actions** *(Proposed)* | Waiting is not work. An agent that starts a 40-minute pipeline completes its run immediately and is resumed with the result; wall-clock waiting never counts against `max_seconds`, or every budget becomes a bet on someone else's CI speed. |

## Reading order

Newcomer: **0002** (how contracts flow) → **0004** and **0005** (the two
subsystems that are not agents) → **0006** (how any of it reaches a human).

Operator: **0001** (where data lives) → **0005** (who can reach what) →
**0006** (what the console does).

## Writing one

`docs/adr/NNNN-kebab-title.md`, numbered sequentially. Status, date, and the
branch it was decided on at the top.

An ADR earns its place by recording the **reasoning**, not the outcome — the
outcome is visible in the code. State what was rejected and why: the next person
will propose it again, and the ADR is the answer. ADR 0006's rejected URL proxy
and ADR 0005's rejected short-lived-credentials-to-agents both exist for that
reason.

Add a row above, and a row in the changelog in
[docs/REPOSITORY_MAP.md](../REPOSITORY_MAP.md).

_Phase: 0 - Scaffold & Tooling_
