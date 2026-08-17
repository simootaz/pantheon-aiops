# Pantheon — Repository Map

**Read this file first, in every session, before touching anything.**

---

## ⚠️ Standing instruction — this file is part of the work

> Whenever you **create, move, rename, or delete a directory or a significant
> file**, you update `docs/REPOSITORY_MAP.md` **in the same commit**:
>
> 1. the [folder map](#folder-map),
> 2. the [Where do I put X?](#where-do-i-put-x) table,
> 3. a new row in the [structure changelog](#structure-changelog).
>
> If you finish a feature branch without touching `docs/REPOSITORY_MAP.md`,
> **you have made a mistake — go back and fix it before merging.**

This instruction lives here so it survives every future session. It is not
optional and it is not a documentation chore: this file is the only artifact
that describes the repository as a whole, and a stale map is worse than none.

---

## Project identity

**Pantheon** is a polyglot, multi-agent AIOps platform. A single orchestrator
(**Zeus**) receives a trigger — an alert, a webhook, a CI failure, a human
question — classifies it, plans which specialists to consult, dispatches them in
parallel, and aggregates their findings into one ranked verdict with proposed
actions. Every write action passes through a guardrail chain before it can touch
a real system.

Agents do not talk to infrastructure directly. They call **connectors**, which
are separate processes exposing tools over **MCP**. That process boundary is what
lets connectors be written in whichever language fits the client library best.

### The eleven agents

| Codename | Folder | Role | Phase |
|---|---|---|---|
| **Zeus** | [core/orchestrator/](../core/orchestrator/) | Orchestrator — routes, classifies, plans, dispatches, aggregates | 2 |
| **Argus** | [agents/anomaly/](../agents/anomaly/) | Detects metric anomalies and correlates them into findings | 1 |
| **Lethe** | [agents/log_clustering/](../agents/log_clustering/) | Clusters high-volume logs into signatures, surfaces novelty | 2 |
| **Hermes** | [agents/nl_query/](../agents/nl_query/) | Translates natural language into connector queries and back | 2 |
| **Hephaestus** | [agents/ci_triage/](../agents/ci_triage/) | Triages failing CI, separates flake from real regression | 4 |
| **Aegis** | [agents/manifest_review/](../agents/manifest_review/) | Reviews Kubernetes manifests and IaC diffs for risk | 3 |
| **Moira** | [agents/capacity/](../agents/capacity/) | Forecasts capacity, predicts saturation | 5 |
| **Mnemosyne** | [agents/knowledge/](../agents/knowledge/) | Recalls prior incidents, runbooks, tribal knowledge | 5 |
| **Clio** | [agents/reporting/](../agents/reporting/) | Writes timelines, postmortems, executive summaries | 5 |
| **Themis** | [agents/dora/](../agents/dora/) | Computes DORA metrics, judges delivery health | 4 |
| **Eris** | [agents/chaos/](../agents/chaos/) | Designs and supervises chaos experiments | 5 |

Zeus is the orchestrator and lives in `core/`, not in `agents/`. The other ten
are domain agents and each owns exactly one folder under `agents/`.

**Delphi** (`core/llm/`) is the LLM gateway and is deliberately *not* on this
list. It is infrastructure that agents consult, not a specialist that Zeus
dispatches to — so it has no roster entry and no `manifest.yaml`. See
[ADR 0004](adr/0004-llm-provider-abstraction.md).

---

## Language boundaries

Three languages, each with a hard boundary. **Do not cross them.**

| Language | Owns | Why |
|---|---|---|
| **Python 3.12** | `core/`, `agents/`, `api/`, `simulator/`, most of `connectors/`, `codegen/` | The agent, LLM and data-science ecosystem is Python. Pydantic v2 gives us one place to define every shape. |
| **Go 1.23** | `pkg/mcpserver/`, `pkg/contracts/`, `connectors/kubernetes/`, `cmd/pantheonctl/`, `cmd/collector/` | `client-go` is the only first-class Kubernetes client. Single static binaries matter for a CLI and a sidecar. |
| **TypeScript** | `dashboard/` — and nowhere else | Next.js 15 App Router. The dashboard is the *only* TypeScript in this repo. |

Tooling per language:

- **Python** — `uv` (env + deps), `ruff` (lint + format), `mypy --strict`, `pytest`
- **Go** — Go workspace (`go.work`), `golangci-lint`
- **TypeScript** — `pnpm`, `biome` (no ESLint, no Prettier), `vitest`

`pnpm` is installed **globally via npm**, not corepack (corepack's `enable`
needs an elevated shell on Windows). The version is pinned once, as
`packageManager` in `dashboard/package.json`; CI's `pnpm/action-setup` reads
it from there rather than pinning a second time, so local and CI cannot drift.

### Go layout and how to build it

**Shared Go libraries live in `pkg/`.** That is the idiomatic home for
importable Go code, and it keeps every Go path free of a leading underscore —
which matters, because the Go tool silently skips `_`-prefixed directories when
expanding a `...` wildcard.

There are **five** Go modules, all under `github.com/simootaz/pantheon-aiops`:

| Module path | Directory |
|---|---|
| `…/pkg/mcpserver` | `pkg/mcpserver` |
| `…/pkg/contracts` | `pkg/contracts` — ⚙️ generated |
| `…/connectors/kubernetes` | `connectors/kubernetes` |
| `…/cmd/pantheonctl` | `cmd/pantheonctl` |
| `…/cmd/collector` | `cmd/collector` |

#### ⚠️ The repo root is not a Go module

`go build ./...` **fails from the repo root** with *"directory prefix . does not
contain modules listed in go.work"*. That is not a broken checkout — the pattern
is invalid there, and adding a root `go.mod` would not fix it: nested modules
are pruned from a parent module's package walk, so it would report success while
building nothing.

**Use these three commands.** Together they cover every module and every
package — this is the definition of done for Go:

```bash
make lint-go                                       # go vet + golangci-lint, per module
make test-go                                       # go build + go test, per module
go build github.com/simootaz/pantheon-aiops/...    # single root-level build
```

`connectors/kubernetes` depends on `pkg/mcpserver`. Neither module is published,
so `go.work` resolves the dependency inside the workspace and a `replace`
directive in `connectors/kubernetes/go.mod` keeps that module building on its
own.

#### Why `connectors/_base/python/` keeps its underscore

The Python base is deliberately **not** moved. Its leading underscore is
load-bearing: `core.registry.loader` discovers connectors by walking
`connectors/*/`, and the underscore marks `_base` as scaffolding rather than a
connector to be registered. `agents/_base/` follows the same convention.

Python has no `...` wildcard to trip over, so the underscore costs nothing there
and earns its keep. Go had no such benefit — only the cost — which is why the Go
base moved to `pkg/mcpserver`.

### The one rule that outranks the others

`core/contracts/` is the **single source of truth** for every cross-language data
shape. Those Pydantic v2 models are exported to JSON Schema, and Go structs and
TypeScript types are **generated** from that schema.

> **Hand-writing a mirrored type in Go or TypeScript is forbidden.**
> If you need a shape in Go or TS that does not exist yet, you add it to
> `core/contracts/` and run `make codegen`. You never type it out twice.

---

## Folder map

Every directory, its purpose, and the phase that implements it.

```
pantheon-aiops/
├── README.md               identity, agent table, architecture diagram, quickstart
├── ARCHITECTURE.md         layer model and the three flows
├── ROADMAP.md              phases 0–7 with exit criteria
├── CONTRIBUTING.md         Git Flow + codegen rules
├── Makefile                every developer entrypoint
├── pyproject.toml          Python project, ruff, mypy, pytest config
├── .python-version         uv's interpreter pin — 3.12, and only 3.12
├── uv.lock                 resolved dependency lock — committed on purpose
├── go.work                 Go workspace over the five Go modules
├── .golangci.yml           Go lint rules, applied to every module
├── .env.example            every environment variable, documented
├── .pre-commit-config.yaml ruff, ruff-format, mypy, gitleaks, codegen drift
└── docs/REPOSITORY_MAP.md  ★ this file — the canonical map
```

| Directory | Purpose | Phase |
|---|---|---|
| **core/** | Python. Everything that is not an agent and not a connector. | 1–5 |
| `core/contracts/` | ★ **Source of truth.** Pydantic v2 models for every cross-language shape. | 1 |
| `core/contracts/export/` | ⚙️ **Generated.** JSON Schema emitted from the models. | 0 |
| `core/orchestrator/` | **Zeus.** `router`, `classifier`, `planner`, `dispatcher`, `aggregator`. | 2 |
| `core/registry/` | Agent manifest discovery and capability matching. | 1 |
| `core/guardrails/` | `policy`, `approval_gate`, `budget` — every write action passes here. Cerberus reuses this Approval Gate; there is no second inbox. | 3 |
| **core/cerberus/** | **Cerberus** — the credential broker. Three heads: `store/` (custody), `policy/` (decisions), `audit/` (memory), plus `broker`, `lease`, `redemption`, `redaction`. Not an agent. | 3 |
| `core/cerberus/store/` | ⛔ **Plaintext.** Agents must not import anything here. | 3 |
| `core/cerberus/redemption.py` | ⛔ **The only producer of plaintext.** Connector-side only. | 3 |
| `core/workflows/` | Temporal `workflow`, `activities`, `worker` for long-running investigations. | 5 |
| `core/memory/` | `vector_store`, `repository`, `cache`. | 2 |
| `core/llm/` | **Delphi** — the LLM gateway. Resolution cascade, capability probing, dialect adapters, shared `prompts/`. Not an agent. Credentials come from Cerberus. | 2 |
| `core/llm/providers/` | Dialect adapters, named by wire format not vendor: `chat_completions` ★, `messages`, `generate_content`, `raw`, `custom`. | 2 |
| `core/observability/` | OTel setup, platform metrics, structured logging. | 1 |
| **agents/** | Python. Ten domain agents, one folder each. | 1–5 |
| `agents/_base/` | `base_agent`, `tool_binding`, `testing` — shared agent scaffolding. | 1 |
| `agents/<domain>/` | One agent: `agent.py`, `manifest.yaml`, `tools.py`, `prompts/`, `tests/`. | varies |
| **connectors/** | Polyglot. Each connector is a separate process speaking MCP. | 1–6 |
| `connectors/_base/python/` | `base_server.py` — base MCP server for Python connectors. The `_` keeps it out of connector auto-discovery. | 1 |
| `connectors/kubernetes/` | **Go.** `cmd/server/`, `internal/{tools,readonly,write,client}/`. | 6 |
| `connectors/kubernetes/python_ref/` | Temporary Python implementation. **Deleted in Phase 6.** | 1 |
| `connectors/prometheus/` | Python. Range/instant queries, series and label discovery. | 1 |
| `connectors/loki/` | Python. LogQL queries and label discovery. | 2 |
| `connectors/alertmanager/` | Python. Active alerts, silences, grouping. | 1 |
| `connectors/gitlab/` | Python. Pipelines, jobs, merge requests, diffs. | 4 |
| `connectors/github/` | Python. Actions runs, pull requests, diffs. | 4 |
| `connectors/litmus/` | Python. Chaos experiment lifecycle and results. | 5 |
| **pkg/** | Go. Shared, importable Go libraries. One module per subdirectory. | 0–6 |
| `pkg/mcpserver/` | Shared MCP server package every Go connector builds on. | 6 |
| `pkg/contracts/` | ⚙️ **Generated.** Go structs from the JSON Schema. Shared by every Go consumer. | 0 |
| **cmd/** | Go binaries. | 6 |
| `cmd/pantheonctl/` | Operator CLI. | 6 |
| `cmd/collector/` | Signal-shipping sidecar. | 6 |
| **api/** | Python. FastAPI: `main.py` (`create_app()` factory), `routers/`, `agui/`, `auth/`, `schemas/`. `/health` is live. | 1–3 |
| `api/agui/` | The AG-UI event endpoint (SSE). **Replaces the bespoke `api/ws/`.** Holds the one unresolved A2UI envelope seam. | 4 |
| **core/ui/** | A2UI surface construction, restricted to the `A2UIComponentType` allowlist. | 4 |
| `core/ui/artifact_resolution.py` | ⛔ **Resolves an ArtifactRef to a signed URL.** Server-side only; agents must not import it. | 4 |
| **dashboard/** | TypeScript. Next.js 15 App Router — the only TS in the repo. | 4 |
| `dashboard/app/` | Routes: `investigations/`, `agents/`, `approvals/`, `settings/`. | 4 |
| `dashboard/lib/agui/` | AG-UI client (`@ag-ui/client` `HttpAgent`) and the Investigation state store: `StateSnapshot` then RFC 6902 `StateDelta`. | 4 |
| `dashboard/components/a2ui/` | The A2UI renderer. Rejects anything outside the allowlist at runtime; `allowlist.ts` asserts at compile time that the allowlist and the **generated** union are the same set, in both directions. | 4 |
| `dashboard/components/` | Shared React components. | 4 |
| `dashboard/lib/` | API client, formatters, hooks. | 4 |
| `dashboard/types/generated/` | ⚙️ **Generated.** TS types from the OpenAPI schema. | 0 |
| **simulator/** | Python. Synthetic metrics, logs and pipelines; scenario runner. | 1 |
| `simulator/scenarios/` | Five YAML scenarios driving the demo and e2e tests. | 1 |
| **codegen/** | The contract pipeline: `export_schemas.py`, `gen_go.sh`, `gen_ts.sh`, `verify.sh`. | 0 |
| **tests/** | Cross-cutting `unit/`, `integration/`, `e2e/`, `fixtures/`. Agent-local tests live in `agents/*/tests/`. | 1–5 |
| **deploy/** | Everything needed to run Pantheon somewhere. | 6–7 |
| `deploy/docker/` | Seven Dockerfiles, one per image. | 6 |
| `deploy/compose/` | Base, dev and observability Compose stacks. | 6 |
| `deploy/helm/pantheon/` | Helm chart: `Chart.yaml`, three values files, `templates/`. | 6 |
| `deploy/kustomize/` | `base/` plus `dev`, `staging`, `prod` overlays. | 6 |
| `deploy/terraform/` | `modules/{network,k8s,postgres,redis,object-storage}`, `envs/{dev,prod}`. Provider-shaped, not vendor-shaped. | 7 |
| `deploy/ansible/` | `playbooks/`, `roles/` for host-level provisioning. | 7 |
| `deploy/argocd/` | Argo CD Applications and projects. | 7 |
| `deploy/observability/` | Grafana dashboards, Prometheus rules, Alertmanager, OTel collector. | 7 |
| `deploy/security/` | Admission policies, sealed secrets, network policies. | 7 |
| `deploy/backup/` | Velero schedule and the Postgres dump CronJob. Both target object storage. | 7 |
| `deploy/scripts/` | `bootstrap-local`, `seed-db`, `smoke-test`, `teardown`. | 6 |
| **.github/** | `workflows/` (9), `ISSUE_TEMPLATE/`, `dependabot.yml`. | 7 |
| `.github/workflows/` | `ci.yml` is the **single required check**; every other workflow is reusable (`workflow_call` only) and is called from it. | 7 |
| **docs/** | `architecture/`, `agents/`, `deployment/`, `adr/`, `diagrams/`. | 7 |
| `docs/REPOSITORY_MAP.md` | ★ **This file.** The canonical map of the repository. | 0 |
| `docs/adr/` | Six Architecture Decision Records, indexed in `docs/adr/README.md`. | 0 |
| `docs/guard-verification.md` | How every guard was verified against a planted violation — including three that turned out not to work. | 0 |

---

## Where do I put X?

| I am adding… | It goes in | Also do |
|---|---|---|
| A new **agent** | `agents/<domain>/` — `agent.py`, `manifest.yaml`, `tools.py`, `prompts/`, `tests/` | Extend `agents/_base/base_agent.py`; register capabilities in `manifest.yaml`; add the codename to the agent table above |
| A new **credential type** | `CredentialType` in `core/contracts/credentials.py` + a handler in `core/cerberus/store/kinds.py` | Never add a field that holds the value |
| Code that needs a **secret** | ❌ **Not in an agent.** | Request a capability via `core.cerberus.broker`; the connector redeems the lease |
| A new **connector** | `connectors/<name>/` — Python unless it needs a Go-only client library | Build on `connectors/_base/python/base_server.py`, or `pkg/mcpserver` for Go |
| A new **shared Go library** | `pkg/<name>/` with its own `go.mod` — never `connectors/_base/` | Add a `use` line to `go.work` |
| A new **contract / data shape** | `core/contracts/<name>.py` — **always here first** | Run `make codegen`; commit the regenerated output |
| A new **LLM provider dialect** | `core/llm/providers/<wire_format>.py` — named by wire format, never by vendor | Add the member to the `Dialect` enum; document which providers speak it |
| A new **LLM provider instance** | ❌ **Nowhere in code.** | Add it from settings as a `ProviderConfig` — that is what `custom.py` exists for |
| A **model name inside an agent** | ❌ **Nowhere.** | Declare `ModelRequirements` and let Delphi resolve — see [ADR 0004](adr/0004-llm-provider-abstraction.md) |
| A new **orchestrator stage** | `core/orchestrator/` | Zeus only — agents never orchestrate each other |
| A new **guardrail or policy** | `core/guardrails/` | Every write action must route through it |
| A new **HTTP endpoint** | `api/routers/<resource>.py` | Request/response bodies come from `core/contracts/`, never redefined |
| A new **event the UI sees** | `core/contracts/events.py`, then map it in `api/agui/translator.py` | Prefer a `StateDelta` on the Investigation. A `Custom` event needs the ADR 0006 test: must the UI *act* on arrival, and is that action not itself an A2UI prompt? |
| A new **agent-rendered UI** | An A2UI surface in `core/ui/`, from the `A2UIComponentType` allowlist | Never raw HTML. Adding a component means adding it to the enum, which is also what the renderer and the advertised capabilities are generated from |
| Anything an agent wants the **browser to fetch** | ❌ **Not a URL.** An `ArtifactRef` to an object Pantheon stored | Resolved server-side in `core/ui/artifact_resolution.py`, same investigation only |
| A new **dashboard route** | `dashboard/app/<route>/page.tsx` | Import types from `dashboard/types/generated/` only |
| A new **React component** | `dashboard/components/` | |
| A new **Helm template** | `deploy/helm/pantheon/templates/` | Add its values to all three `values*.yaml`; `helm lint` must pass |
| A new **Terraform module** | `deploy/terraform/modules/<name>/` | Wire it into `envs/dev` and `envs/prod`; `terraform fmt` must pass |
| A new **container image** | `deploy/docker/Dockerfile.<name>` | Add the service to the Compose stack |
| A new **CI check** | `.github/workflows/<name>.yml`, `workflow_call` only | Add it to `ci.yml`'s jobs **and** to `gate.needs`, plus `REQUIRED_CHECKS` in `tests/unit/test_ci_workflows.py`. Never give it its own triggers — every job would run twice per PR |
| A new **simulator scenario** | `simulator/scenarios/<name>.yaml` | |
| A new **cross-cutting test** | `tests/{unit,integration,e2e}/` | Agent-specific tests belong in `agents/<domain>/tests/` |
| A new **Go module** | Its own directory with a `go.mod` under `github.com/simootaz/pantheon-aiops/<path>` | Add a `use` line to `go.work`. `make test-go` / `make lint-go` pick it up automatically |
| A new **Go package** in an existing module | `internal/` for module-private, `pkg/` for importable | Never `pkg/contracts/` — that is generated |
| A new **architecture decision** | `docs/adr/NNNN-<title>.md` | Number sequentially; link it from the changelog row in docs/REPOSITORY_MAP.md |
| A **Go type mirroring a Python model** | ❌ **Nowhere.** | Add it to `core/contracts/` and generate it |
| Anything touching **object storage** | Any S3-compatible client against `S3_ENDPOINT_URL` | See [Standing decisions](#standing-decisions). Never hardcode an AWS endpoint or region |

---

## Generated files — never hand-edit

Three directories contain **only** machine-generated output. Editing them by hand
is a bug that CI will catch.

| File | Generated from | By | Generator pinned at |
|---|---|---|---|
| `core/contracts/export/pantheon.schema.json` | `core/contracts/*.py` (Pydantic v2) | `codegen/export_schemas.py` | `pydantic>=2.9` |
| `pkg/contracts/contracts.gen.go` | the JSON Schema above | `codegen/gen_go.sh` | `go-jsonschema` `v0.24.1` |
| `dashboard/types/generated/contracts.ts` | the JSON Schema above | `codegen/gen_ts.sh` | `json-schema-to-typescript` `15.0.4` |

**Both generators read the same JSON Schema — not OpenAPI.** That is one drift
surface, guarded by one verifier. See
[ADR 0002](adr/0002-codegen-from-json-schema.md). Generator versions are
pinned on purpose: an unpinned tool changes its output on upgrade, which is
indistinguishable from a real contract change.

`codegen/verify.sh` regenerates everything into a temp directory and diffs it
against the committed output. **Any drift fails the build.** It runs in
pre-commit and in the `codegen-check` workflow.

To change any of these: edit `core/contracts/`, run `make codegen`, commit both
the contract change and the regenerated output together.

---

## Standing decisions

Cross-cutting rules that outlive any one branch. Each links to its ADR.

### The repository claims no AI authorship

[ADR 0003](adr/0003-neutral-repository-documentation.md) · live now

No tracked file claims to have been authored or generated by an assistant, and
no commit message does either. This file, `docs/REPOSITORY_MAP.md`, is the
canonical map; a root-level pointer file is permitted but excluded per-clone via
`.git/info/exclude`, never tracked.

**The ban targets attribution, not vendors.** Vendor names, model identifiers,
API endpoint hosts and provider documentation are *product content* and are
explicitly allowed anywhere — Pantheon is an LLM platform, so naming providers
is describing the software. What is banned is a co-author trailer naming an
assistant, a "generated by" footer, an emoji sign-off, or a reference to an
assistant's pointer file or config directory.

> **The rule:** enforced by `tests/unit/test_repo_neutrality.py`, which matches
> attribution *patterns* across every `git ls-files` path and its contents. Its
> own behaviour is tested in both directions, so it cannot be quietly
> re-broadened into a vendor ban or hollowed out.

### Delphi — agents never name a model

[ADR 0004](adr/0004-llm-provider-abstraction.md) · structure Phase 0, behaviour Phase 2

`core/llm/` is **Delphi**, the LLM gateway. It sits beside the orchestrator as
infrastructure — it is **not** an agent, has no entry in the eleven-agent roster
and ships no `manifest.yaml`.

Agents declare `ModelRequirements` — capabilities, minimum context, tier, max
cost per call — and Delphi resolves them to a concrete model at call time via
per-task override → per-agent binding → tier default → global default. On
failure: fallback chain → budget guard → hard stop, never a silent downgrade.

> **The rule:** an agent that names a model is a bug. Swapping providers in
> settings must require zero code changes across all eleven agents. Capabilities
> are **probed**, never hardcoded — a model table would be stale in weeks and
> would exclude every model released after it was written.

### The UI speaks two open protocols

[ADR 0006](adr/0006-agentic-ui-protocols.md) · structure Phase 0, behaviour Phase 4

**AG-UI is the transport and runtime; A2UI is the payload for agent-generated
UI.** That division is the thing people get wrong. Most of what Pantheon emits is
ordinary AG-UI — lifecycle, findings, tool calls, state. A2UI appears only when
an agent needs a human to see or decide something.

**The shared state object is the `Investigation`**: `StateSnapshot` at
`RunStarted`, `StateDelta` (RFC 6902) thereafter. Naming it prevents a second
state object being invented later, and makes replay a property of the design —
snapshot plus ordered patches reconstructs any run.

**AG-UI's event types are never redefined here.** They come from `ag_ui.core`.

There is exactly **one** `Custom` event, `pantheon.break_glass`, and the bar for
adding another is: *must the UI act the moment it arrives, and is that action not
itself an A2UI prompt?*

> **The rule:** agent-generated UI is **untrusted data, not code**. The host
> renders only from the closed `A2UIComponentType` allowlist — no HTML, no
> script, no free-form styling. No agent-rendered component may request
> credentials or approvals outside the Cerberus and Approval Gate paths.
> `iconUrl` and `agentDisplayName` are set by the orchestrator, never by an
> agent, so no agent can impersonate another or impersonate Pantheon.
>
> **Media is reference-based.** `Image` takes an `ArtifactRef` — an object key
> for an artifact Pantheon produced — never a URL. An agent-authored URL is an
> exfiltration channel, and a proxy that filters URLs is one bypass from
> failing; a reference has nothing to filter. Same pattern as `CredentialRef`.

### Agents never hold credentials

[ADR 0005](adr/0005-credential-brokering.md) · structure Phase 0, behaviour Phase 3

`core/cerberus/` is **Cerberus**, the credential broker. Three heads: store,
policy, audit. Infrastructure like Delphi — not an agent, no roster entry, no
`manifest.yaml`.

An agent asks for a **capability** (target, action, and the hypothesis it is
testing). Cerberus evaluates the grant, routes to the existing Approval Gate if
there is none, and mints a **lease bound to one connector and one
investigation**. The connector redeems the lease; the agent receives **results
only**.

The reason is specific: a secret in an agent's context becomes part of a prompt,
which is sent to a model provider and logged there. That is an unauditable,
unrevocable exfiltration path — so the threat model assumes the agent is fully
prompt-injected and requires that it cannot leak what it never held.

**Data-flow claim, precisely.** `AuditEntry` is attached to `Investigation`,
which agents *do* see. That is safe because every credential in it is a
`CredentialRef` — an identifier, never a value — and because plaintext has no
contract representation at all. `tests/unit/test_credential_safety.py` is what
keeps that true: it scans the generated JSON Schema, Go **and** TypeScript for
any secret-shaped property.

**Allowed import surface for agents:** `core.cerberus.broker` and
`core.cerberus.redaction`, and nothing else. `redemption` and `store/` are off
limits, enforced at the import graph rather than by convention.

> **The rule:** an agent that receives credential plaintext is a security bug.
> Provider API keys are Cerberus credentials too — Delphi ships no secret store
> of its own.

### Codegen reads JSON Schema, never OpenAPI

[ADR 0002](adr/0002-codegen-from-json-schema.md) · live now

Go and TypeScript domain types are both generated from
`core/contracts/export/pantheon.schema.json`. The dashboard needs `Finding`,
`Verdict` and `Investigation` as domain types regardless of which route returns
them; OpenAPI-derived types would be shaped by routing accidents. One artifact
means one drift surface and one verifier.

Endpoint-surface types — paths, params, status codes — are a **separate,
additive** generator arriving at Phase 1 as `codegen/gen_ts_api.sh`. It sits
*beside* the domain types, never on top of them.

> **The rule:** to change a shape in Go or TypeScript, edit `core/contracts/`
> and run `make codegen`. Commit the contract change and the regenerated output
> together. `codegen/verify.sh` fails the build otherwise, in pre-commit and CI.

### Object storage is MinIO — never a cloud dependency

[ADR 0001](adr/0001-object-storage-minio.md) · applies from Phase 6

Pantheon must run **fully self-hosted with zero cloud accounts**. MinIO is the
default S3 layer everywhere: Compose ships `minio` + a `minio-init` one-shot
creating `pantheon-reports`, `pantheon-artifacts` and `pantheon-backups`; Helm
exposes a `minio:` block (`enabled: true`, with `external.endpoint` /
`external.region` / `existingSecret` for swapping in a real provider);
Terraform's `object-storage/` module is provider-shaped, not AWS-shaped.

Application code uses `boto3` or `minio-py` against a configurable
`S3_ENDPOINT_URL`. Config lives in `.env.example` as `S3_ENDPOINT_URL`,
`S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_BUCKET_REPORTS`,
`S3_BUCKET_ARTIFACTS`, `S3_BUCKET_BACKUPS`, `S3_USE_SSL`.

> **The rule:** any S3-compatible endpoint must work. Do not couple to MinIO's
> own SDK features beyond what the S3 API gives you. `mc` is allowed only in the
> Compose init container and in `deploy/scripts/` — never in `core/`, `agents/`,
> `api/` or `connectors/`.

---

## Git Flow rules

This repo uses Git Flow. `main` and `develop` already exist.

- **NEVER commit directly to `develop` or `main`.**
- Every unit of work starts a feature branch:
  ```bash
  git checkout develop && git pull && git checkout -b feature/<name>
  ```
- Commit inside the feature branch with **conventional commits**:
  `feat:`, `chore:`, `docs:`, `test:`, `build:`
- When the feature is complete **and its checks pass**:
  ```bash
  git checkout develop && git merge --no-ff feature/<name> && git branch -d feature/<name>
  ```
- **Announce the branch name before starting it**, and confirm the merge and
  deletion when finishing it.

---

## Commands

Every Makefile target. Targets are wired branch by branch during Phase 0; a
target that is not yet wired says so and exits non-zero.

| Target | Does | Live? |
|---|---|---|
| `make help` | List every target (default goal) | ✅ |
| `make install` | `uv sync` + `pre-commit install`. Go has no external deps; dashboard deps land on branch 4 | ✅ |
| `make dev` | Run the API locally with reload (`uvicorn --factory`, `/health` live) | ✅ |
| `make sim` | Run a simulator scenario against the local stack | ⏳ needs `simulator.cli` (Phase 1) |
| `make test` | `pytest` with coverage | ✅ |
| `make test-go` | `go build` + `go test` in every module listed in `go.work` | ✅ |
| `make test-ts` | Dashboard test suite (`vitest`) | ⏳ branch 4 |
| `make lint` | `ruff check` + `ruff format --check` | ✅ |
| `make lint-go` | `go vet` + `golangci-lint` in every module listed in `go.work` | ✅ |
| `make lint-ts` | `biome` against the dashboard | ⏳ branch 4 |
| `make typecheck` | `mypy --strict` over the Python tree | ✅ |
| `make codegen` | Regenerate JSON Schema, Go structs and TS types | ✅ |
| `make codegen-verify` | Fail if generated output has drifted | ✅ |
| `make up` | Start the local Compose stack | ⏳ branch 6 |
| `make down` | Stop the local Compose stack | ⏳ branch 6 |
| `make clean` | Remove build artifacts and tooling caches | ✅ |

A target that is not live names what it is waiting on and exits non-zero. None
of them silently succeed.

### Python environment

`uv` owns the environment. `.python-version` pins **3.12** and `pyproject.toml`
declares `requires-python = ">=3.12,<3.13"` — the platform is validated against
exactly one minor version, so the upper bound is deliberate, not an oversight.
Run tools through `uv run` (or `make`), never against a system interpreter.

`make install` runs `pre-commit install` for you. All five hooks — ruff-check,
ruff-format, mypy, gitleaks and the codegen drift check — are live and passing.

---

## Phase roadmap

| Phase | Name | Delivers |
|---|---|---|
| **0** | **Scaffold & Tooling** ← **current** | Repo structure, Python/Go/TS tooling, codegen pipeline, deploy skeleton, CI, docs |
| 1 | Contracts & First Agent Path | `core/contracts/` filled, registry, `agents/_base/`, **Argus**, Prometheus + Alertmanager connectors, API skeleton, metric/log simulator |
| 2 | Orchestrator & Investigation Flow | **Zeus** end to end, memory, LLM provider, **Lethe** + **Hermes**, Loki connector |
| 3 | Guardrails, Approvals & Write Actions | `core/guardrails/`, **Aegis**, write tools, approvals API + WebSocket stream, auth |
| 4 | Delivery Flow | **Hephaestus** + **Themis**, GitLab + GitHub connectors, pipeline simulator, dashboard investigation UI |
| 5 | Proactive Flow | **Moira**, **Mnemosyne**, **Clio**, **Eris**, Litmus connector, Temporal workflows, e2e tests |
| 6 | Go Port & Platform Binaries | Kubernetes connector in Go (`python_ref/` deleted), `pantheonctl`, `collector`, Docker + Compose + Helm |
| 7 | Production Hardening | Terraform, Argo CD, Ansible, observability dashboards, security policies, backup, release automation |

### Phase 0 branch order

Phase 0 ships as eight feature branches. Branch 3 was pulled ahead of branch 2
because the Python toolchain was not yet installed while Go 1.23 already was, so
`feature/go-workspace` could be fully verified and `feature/python-tooling`
could not. See [ROADMAP.md](../ROADMAP.md#phase-0-branch-order).

| Order | Branch | Status |
|---|---|---|
| 1 | `feature/repo-skeleton` | ✅ merged |
| 2 | `feature/go-workspace` | ✅ merged *(was 3rd)* |
| — | `feature/go-base-relocation` | ✅ merged — unplanned; moved the shared Go library to `pkg/mcpserver` |
| 3 | `feature/python-tooling` | ✅ merged *(was 2nd)* |
| 4 | `feature/dashboard-scaffold` | 🚧 **blocked** — `corepack enable` needs an elevated shell; pnpm unavailable |
| 5 | `feature/codegen-pipeline` | ✅ merged |
| — | `feature/api-minimal` | ✅ merged — unplanned; `create_app()` + `/health`, makes `make dev` live |
| 6 | `feature/deploy-skeleton` | ⏳ |
| 7 | `feature/ci-workflows` | ⏳ |
| 8 | `feature/docs-baseline` | ⏳ |

---

## Structure changelog

Every structural change gets a row. Date, what changed, which branch, which files.

| Date | Branch | Change |
|---|---|---|
| 2026-08-15 | `feature/sarif-code-scanning` | **Security findings go to code scanning.** `security.yml` now uploads SARIF via `github/codeql-action/upload-sarif` (SHA-pinned) instead of attaching artifacts, with a **distinct `category` per scanner** — GitHub keys results by (tool, category), so a shared category silently replaces the previous scanner's alerts. Each scan runs `continue-on-error` and fails in a later step, so findings upload even when the scan fails. bandit gains SARIF via `bandit-sarif-formatter`, since bandit emits no SARIF natively. `ci.yml` grants `security-events: write` to the `security` job as well, because a called workflow cannot exceed its caller — omitting it would 403 the uploads while every scan still reported green. The SBOM stays an artifact: it is an inventory, not findings. Two new guards, both verified against planted violations. Retires the SARIF row from ROADMAP. |
| 2026-08-15 | `feature/docs-baseline` | **Docs baseline, and a guard audit.** Audited all 78 guards against planted violations in both directions. Found one real bug class affecting three guards: each asserted a substring that also appeared in the *comment* describing it, so deleting the real mechanism left them green — verified by removing every `fail()` call from `validation.yaml`, the `resource-policy` annotation from `minio-secret.yaml`, and the whole warning block from `application.yaml`. Fixed with a `_mechanism_only()` helper that strips comments before mechanism assertions. Five further reports were faults in the audit harness, not the guards. Wrote `README.md` (honest Phase 0 status, agent table, mermaid architecture), `ARCHITECTURE.md` (three flows, contract pipeline, user boundary), `ROADMAP.md` (phases 0–7 plus every deferred row), `CONTRIBUTING.md` (Git Flow, codegen, guard philosophy), `docs/adr/README.md` and `docs/guard-verification.md`. |
| 2026-08-15 | `feature/dashboard-scaffold` | **Dashboard scaffolded.** Next.js 15.5.23 App Router, React 19, TypeScript 5.9 strict (`noUncheckedIndexedAccess`), Tailwind 4, biome 2.5 (no ESLint/Prettier), vitest 4. Four route pages plus a root layout. Added `dashboard/lib/agui/` — `@ag-ui/client` `HttpAgent` and an `InvestigationStore` applying `StateSnapshot` then RFC 6902 `StateDelta` — and `dashboard/components/a2ui/` — the renderer, switching exhaustively over the generated `A2UIComponentType` with a `never` exhaustiveness check, plus `allowlist.ts` which re-exports rather than restates the generated union. 12 TypeScript tests including the out-of-allowlist rejection. `ci-dashboard.yml` no longer no-ops; `make lint-ts`, `test-ts` and `install` wired. pnpm pinned once via `packageManager`. Declared `sharp` build script off — `next/image` is unused because A2UI images resolve through an ArtifactRef. |
| 2026-08-15 | `feature/artifact-backed-media` | **Media re-admitted, reference-based.** `Image` returns to the allowlist taking an `ArtifactRef` — an object key for an artifact Pantheon produced — never a URL. Added `ArtifactRef`/`ArtifactKind` to `core/contracts/ui.py` and `core/ui/artifact_resolution.py`, whose import is forbidden to agents, mirroring `core.cerberus.redemption`. `Video` and `AudioPlayer` stay out. New guards: `ArtifactRef` cannot express a destination, no A2UI component accepts a free-form URL in **any** language, and the resolver is off limits to agents — all verified against planted violations. ADR 0006 records that a URL proxy was considered and rejected. Both ADR 0005 and 0006 now state that the schema scan and redaction cover different halves of one threat. |
| 2026-08-15 | `feature/agentic-ui-protocols` | **Agentic UI protocols.** Added `core/contracts/ui.py` (A2UI allowlist as a generated contract, surface, component, action, client capabilities), `api/agui/` (endpoint, translator, and the isolated A2UI envelope seam) and `core/ui/` (surface builders, Approval Gate and Cerberus access-request surfaces). **Deleted `api/ws/`** — the bespoke WebSocket protocol is superseded by AG-UI. Pinned `ag-ui-protocol>=0.1.20,<0.2`; A2UI **v0.9.1**, not the v1.0 release candidate. Added `tests/unit/test_agentic_ui.py` (13 guards): allowlist rejection, media/Modal exclusions, allowlist reaches TypeScript, capabilities equal the allowlist, identity not settable by agents, no bespoke WS returns, AG-UI events not redefined, envelope guess isolated to one seam, and redaction covering A2UI payloads. See [ADR 0006](adr/0006-agentic-ui-protocols.md). |
| 2026-08-15 | `feature/cerberus-credential-brokering` | **Cerberus.** Added `core/cerberus/` — three heads (`store/`, `policy/`, `audit/`) plus `broker`, `lease`, `redemption` and `redaction`, including `store/rotation.py` and `policy/revocation.py` (break-glass). `redaction.py` is **implemented, not stubbed**. Added `core/contracts/credentials.py` (7 contracts) and an `audit` trail on `Investigation`. **Deleted `core/llm/keyring.py`** with no shim; updated all nine references. Renamed contract fields `credential` → `credential_ref` so the name states the invariant. Added `tests/unit/test_credential_safety.py` — schema scan across JSON Schema/Go/TS, an import-graph boundary guard, and a planted-secret redaction test. Licence stated as **Apache-2.0** in `pyproject.toml` (was MIT), `Chart.yaml` and the README badge. See [ADR 0005](adr/0005-credential-brokering.md). |
| 2026-08-15 | `feature/ci-workflows` | **CI.** Nine workflows: `ci.yml` (the single required check) plus reusable `ci-python`, `ci-go`, `ci-dashboard`, `codegen-check`, `ci-deploy`, `security`, and non-firing `build-push` / `release` stubs. Every action pinned to a commit SHA; `permissions` scoped per job with an empty default; per-workflow per-ref concurrency; uv, Go and pnpm caches. `codegen-check` asserts its generator pins equal those in `codegen/gen_*.sh` and fails loudly on divergence. `ci-deploy` additionally asserts the chart fails closed without credentials and that Ollama stays behind its profile. `dependabot.yml` covers pip, five gomod modules, npm, actions and docker. Added `tests/unit/test_ci_workflows.py` (8 guards). Gated with actionlint and zizmor — both clean. |
| 2026-08-15 | `fix/generated-credential-policy` | **Chart fails closed on generated credentials.** The generated MinIO secret sits behind `lookup`, which is empty on any *client-side* render — `helm template`, `helm diff`, Argo CD's default mode — so each sync would mint a new password, register drift, rewrite the secret and orphan the stored data. Added `productionMode` (true in `values-prod.yaml`) and `templates/validation.yaml`, which refuses to render when a required secret is missing; annotated the generated secret `helm.sh/resource-policy: keep` plus Argo CD sync options and marked it dev-only; documented the trap in `deploy/argocd/application.yaml`. Four new structural guards. |
| 2026-08-15 | `feature/deploy-skeleton` | **Deploy skeleton and Delphi structure.** Filled `deploy/` end to end: 7 Dockerfiles, 3 Compose files (with `minio` + `minio-init` bucket bootstrap and an optional `ollama` profile), a Helm chart that lints and templates under three value sets, kustomize base + 3 overlays, 5 Terraform modules + 2 envs, Argo CD Application/AppProject, Ansible skeleton, observability configs, network policies, and Velero + Postgres backup jobs. **Renamed `deploy/terraform/modules/s3/` → `modules/object-storage/`** and made it provider-shaped (ADR 0001, now applied). Added **Delphi** under `core/llm/` — `gateway`, `resolver`, `fallback`, `capability_matrix`, `probe`, `keyring`, `catalog` plus `providers/{chat_completions,messages,generate_content,raw,custom}` — and `core/contracts/llm.py` with six contracts flowing through codegen. **Renamed `Capability` → `AgentCapability`** in `manifest.py` to avoid a flat-namespace collision with Delphi's `Capability` in generated Go and TS. Wired `make up` / `make down`. Extended the structural guards to 13. |
| 2026-08-15 | `feature/neutrality-guard-narrowing` | **Guard narrowed; Delphi specced.** Rewrote `tests/unit/test_repo_neutrality.py` to match authorship-*attribution patterns* instead of banning vendor substrings — the old shape blocked legitimate product content (provider tables, model ids, endpoint hosts) while catching nothing extra. The guard's own behaviour is now tested in both directions. Amended [ADR 0003](adr/0003-neutral-repository-documentation.md) with the reasoning, and added [ADR 0004](adr/0004-llm-provider-abstraction.md) specifying **Delphi**, the LLM gateway. `core/llm/` structure and `core/contracts/llm.py` land on `feature/deploy-skeleton`. |
| 2026-08-15 | `docs/adr-0003-addendum` | **History rewritten.** One `git filter-repo` pass stripped tool co-author trailers from 36 of 45 commits and substituted the old map filename in 10 message lines. Tree hashes of `develop` and `main` unchanged — metadata only. Recorded as an addendum to [ADR 0003](adr/0003-neutral-repository-documentation.md). |
| 2026-08-15 | `feature/repo-map-neutralization` | **Repository map moved and neutralised.** The root map file moved to `docs/REPOSITORY_MAP.md` (all nine sections intact, relative links re-based one level deeper); the root file is now an untracked local pointer, dropped from the index with `git rm --cached` rather than deleted from disk. Local pointer files are excluded per-clone via `.git/info/exclude` rather than `.gitignore` — naming them in a tracked file would reintroduce the very fingerprint being removed. Retargeted every reference in `README.md`, `ROADMAP.md`, `CONTRIBUTING.md`, ADR 0002 and `tests/unit/test_repo_structure.py` (incl. renaming a test function). Made LLM environment config provider-neutral in `.env.example`. Added `tests/unit/test_repo_neutrality.py` (3 guards) and [ADR 0003](adr/0003-neutral-repository-documentation.md). |
| 2026-08-15 | `feature/api-minimal` | **API skeleton.** `api/main.py` gains `create_app()`; `api/routers/health.py` serves `GET /health`; `api/schemas/common.py` gains `HealthResponse`; `api/__init__.py` gains `__version__`. Added `tests/unit/test_api_health.py` (3 tests, incl. asserting the OpenAPI document builds — Phase 1's `gen_ts_api.sh` depends on it). Added `fastapi` + `uvicorn` runtime deps and `httpx` dev dep. **`make dev` is now live**, verified serving 200 on `/health`. Switched the pre-commit mypy hook from `mirrors-mypy` to a local `uv run mypy` hook — the isolated venv's `additional_dependencies` drifted from the project's every time a dependency was added, failing at commit time while `make typecheck` stayed green. |
| 2026-08-15 | `feature/codegen-pipeline` | **Codegen pipeline live.** Filled `core/contracts/` with minimal-but-real Pydantic v2 models, added `core/contracts/base.py` (`ContractModel`, `extra="forbid"`). Implemented `export_schemas.py`, `gen_go.sh`, `gen_ts.sh`, `verify.sh`. New generated artifacts: `core/contracts/export/pantheon.schema.json`, `pkg/contracts/contracts.gen.go`, `dashboard/types/generated/contracts.ts`. **Added module `pkg/contracts/`** (5th Go module) and **deleted `connectors/kubernetes/pkg/`** — shared contracts must not live inside one connector. Wired `make codegen` / `codegen-verify`, enabled the codegen pre-commit hook and added `pre-commit install` to `make install`. Extended `tests/unit/test_repo_structure.py` with three codegen guards. See [ADR 0002](adr/0002-codegen-from-json-schema.md). |
| 2026-08-15 | `feature/codegen-pipeline` | **Spec corrected.** `gen_ts.sh` generates from JSON Schema, not from the FastAPI OpenAPI document. Endpoint-surface types become a separate additive generator, `codegen/gen_ts_api.sh`, at Phase 1. |
| 2026-08-14 | `feature/python-tooling` | **Python toolchain.** Filled `pyproject.toml` (ruff `E,F,I,B,UP,SIM,RUF` @ 100, mypy `strict`, pytest + coverage, `dependency-groups.dev`) and `.pre-commit-config.yaml` (ruff-check, ruff-format, mypy, gitleaks, codegen drift). Added `.python-version` (3.12) and `uv.lock`, both committed. Added `tests/unit/test_repo_structure.py` — five guards over the agent roster, package initialisers, phase markers and generated-directory banners. Wired `make install`, `test`, `lint`, `typecheck`; `dev` and `sim` stay stubs until Phase 1 supplies `api.main:app` and `simulator.cli`. Rewrapped five over-length docstrings in `api/`, `core/` flagged by ruff. |
| 2026-08-14 | `feature/go-base-relocation` | **Moved `connectors/_base/go/` → `pkg/mcpserver/`** (module `github.com/simootaz/pantheon-aiops/pkg/mcpserver`). `pkg/` is the idiomatic home for shared Go libraries, and the move removes the `_`-wildcard trap outright instead of documenting it. Updated `go.work`, `connectors/kubernetes/go.mod` (require + replace → `../../pkg/mcpserver`) and the three importing files; the import alias is no longer needed. `connectors/_base/python/` **stays** — its underscore is load-bearing for connector auto-discovery. Rewrote the Go section of docs/REPOSITORY_MAP.md accordingly and corrected `connectors/_base/__init__.py`, which still claimed to host both languages. **Supersedes the wildcard guidance in the `feature/go-workspace` row below.** |
| 2026-08-14 | `feature/go-base-relocation` | **Definition of done corrected.** Dropped `go build ./...` — it cannot work from a non-module root. Replaced everywhere by the three commands that genuinely cover every module: `make lint-go`, `make test-go`, `go build github.com/simootaz/pantheon-aiops/...`. Branch 7 must use these in CI. |
| 2026-08-14 | `feature/go-workspace` | **Rename recorded as pending** — `deploy/terraform/modules/s3/` → `modules/object-storage/`. ✅ **Applied on `feature/deploy-skeleton`**, see the row above. |
| 2026-08-14 | `feature/go-workspace` | **Standing decision: object storage is MinIO.** Added `docs/adr/0001-object-storage-minio.md` and removed the now-redundant `docs/adr/.gitkeep`. Added a *Standing decisions* section here and an object-storage row to the *Where do I put X?* table. |
| 2026-08-14 | `feature/go-workspace` | **Branch order changed.** Branch 3 pulled ahead of branch 2 — the Python toolchain was not installed yet, so `feature/python-tooling` could not be verified while `feature/go-workspace` could. Recorded in ROADMAP.md and the phase roadmap above. |
| 2026-08-14 | `feature/go-workspace` | **Go workspace.** Added root `.golangci.yml` and four `go.mod` files (`connectors/_base/go`, `connectors/kubernetes`, `cmd/pantheonctl`, `cmd/collector`), all under `github.com/simootaz/pantheon-aiops`. Filled `go.work` with its `use` block. Replaced the Go placeholders with compiling stubs. Wired `make test-go` and `make lint-go` to iterate `go.work`. Documented that the repo root is not a module and that `_base/` is skipped by `...` wildcards. |
| 2026-08-14 | `feature/repo-skeleton` | **Initial tree.** Created `core/`, `agents/` (10 domains + `_base`), `connectors/` (7 + `_base`), `cmd/`, `api/`, `dashboard/`, `simulator/`, `codegen/`, `tests/`, `deploy/`, `.github/`, `docs/`. Added the root repository map, `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `Makefile`, `pyproject.toml`, `go.work`, `.env.example`, `.gitignore`, `.dockerignore`, `.editorconfig`, `.pre-commit-config.yaml`. Every Python package has `__init__.py`; every intentionally empty directory has `.gitkeep`; the three generated directories have a `README.md` instead. |
