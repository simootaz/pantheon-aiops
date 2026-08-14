# CLAUDE.md — Pantheon living map

**Read this file first, in every session, before touching anything.**

---

## ⚠️ Standing instruction — this file is part of the work

> Whenever you **create, move, rename, or delete a directory or a significant
> file**, you update `CLAUDE.md` **in the same commit**:
>
> 1. the [folder map](#folder-map),
> 2. the [Where do I put X?](#where-do-i-put-x) table,
> 3. a new row in the [structure changelog](#structure-changelog).
>
> If you finish a feature branch without touching `CLAUDE.md`, **you have made a
> mistake — go back and fix it before merging.**

This instruction lives here so it survives every future session. It is not
optional and it is not a documentation chore: `CLAUDE.md` is the only artifact
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
| **Zeus** | [core/orchestrator/](core/orchestrator/) | Orchestrator — routes, classifies, plans, dispatches, aggregates | 2 |
| **Argus** | [agents/anomaly/](agents/anomaly/) | Detects metric anomalies and correlates them into findings | 1 |
| **Lethe** | [agents/log_clustering/](agents/log_clustering/) | Clusters high-volume logs into signatures, surfaces novelty | 2 |
| **Hermes** | [agents/nl_query/](agents/nl_query/) | Translates natural language into connector queries and back | 2 |
| **Hephaestus** | [agents/ci_triage/](agents/ci_triage/) | Triages failing CI, separates flake from real regression | 4 |
| **Aegis** | [agents/manifest_review/](agents/manifest_review/) | Reviews Kubernetes manifests and IaC diffs for risk | 3 |
| **Moira** | [agents/capacity/](agents/capacity/) | Forecasts capacity, predicts saturation | 5 |
| **Mnemosyne** | [agents/knowledge/](agents/knowledge/) | Recalls prior incidents, runbooks, tribal knowledge | 5 |
| **Clio** | [agents/reporting/](agents/reporting/) | Writes timelines, postmortems, executive summaries | 5 |
| **Themis** | [agents/dora/](agents/dora/) | Computes DORA metrics, judges delivery health | 4 |
| **Eris** | [agents/chaos/](agents/chaos/) | Designs and supervises chaos experiments | 5 |

Zeus is the orchestrator and lives in `core/`, not in `agents/`. The other ten
are domain agents and each owns exactly one folder under `agents/`.

---

## Language boundaries

Three languages, each with a hard boundary. **Do not cross them.**

| Language | Owns | Why |
|---|---|---|
| **Python 3.12** | `core/`, `agents/`, `api/`, `simulator/`, most of `connectors/`, `codegen/` | The agent, LLM and data-science ecosystem is Python. Pydantic v2 gives us one place to define every shape. |
| **Go 1.23** | `pkg/mcpserver/`, `connectors/kubernetes/`, `cmd/pantheonctl/`, `cmd/collector/` | `client-go` is the only first-class Kubernetes client. Single static binaries matter for a CLI and a sidecar. |
| **TypeScript** | `dashboard/` — and nowhere else | Next.js 15 App Router. The dashboard is the *only* TypeScript in this repo. |

Tooling per language:

- **Python** — `uv` (env + deps), `ruff` (lint + format), `mypy --strict`, `pytest`
- **Go** — Go workspace (`go.work`), `golangci-lint`
- **TypeScript** — `pnpm`, `biome` (no ESLint, no Prettier), `vitest`

### Go layout and how to build it

**Shared Go libraries live in `pkg/`.** That is the idiomatic home for
importable Go code, and it keeps every Go path free of a leading underscore —
which matters, because the Go tool silently skips `_`-prefixed directories when
expanding a `...` wildcard.

There are **four** Go modules, all under `github.com/simootaz/pantheon-aiops`:

| Module path | Directory |
|---|---|
| `…/pkg/mcpserver` | `pkg/mcpserver` |
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
├── CLAUDE.md               this file — the living map
├── README.md               identity, agent table, architecture diagram, quickstart
├── ARCHITECTURE.md         layer model and the three flows
├── ROADMAP.md              phases 0–7 with exit criteria
├── CONTRIBUTING.md         Git Flow + codegen rules
├── Makefile                every developer entrypoint
├── pyproject.toml          Python project, ruff, mypy, pytest config
├── go.work                 Go workspace over the four Go modules
├── .golangci.yml           Go lint rules, applied to every module
├── .env.example            every environment variable, documented
├── .pre-commit-config.yaml ruff, ruff-format, mypy, gitleaks, codegen drift
```

| Directory | Purpose | Phase |
|---|---|---|
| **core/** | Python. Everything that is not an agent and not a connector. | 1–5 |
| `core/contracts/` | ★ **Source of truth.** Pydantic v2 models for every cross-language shape. | 1 |
| `core/contracts/export/` | ⚙️ **Generated.** JSON Schema emitted from the models. | 0 |
| `core/orchestrator/` | **Zeus.** `router`, `classifier`, `planner`, `dispatcher`, `aggregator`. | 2 |
| `core/registry/` | Agent manifest discovery and capability matching. | 1 |
| `core/guardrails/` | `policy`, `approval_gate`, `budget` — every write action passes here. | 3 |
| `core/workflows/` | Temporal `workflow`, `activities`, `worker` for long-running investigations. | 5 |
| `core/memory/` | `vector_store`, `repository`, `cache`. | 2 |
| `core/llm/` | Provider abstraction, tracing, and shared `prompts/`. | 2 |
| `core/observability/` | OTel setup, platform metrics, structured logging. | 1 |
| **agents/** | Python. Ten domain agents, one folder each. | 1–5 |
| `agents/_base/` | `base_agent`, `tool_binding`, `testing` — shared agent scaffolding. | 1 |
| `agents/<domain>/` | One agent: `agent.py`, `manifest.yaml`, `tools.py`, `prompts/`, `tests/`. | varies |
| **connectors/** | Polyglot. Each connector is a separate process speaking MCP. | 1–6 |
| `connectors/_base/python/` | `base_server.py` — base MCP server for Python connectors. The `_` keeps it out of connector auto-discovery. | 1 |
| `connectors/kubernetes/` | **Go.** `cmd/server/`, `internal/{tools,readonly,write,client}/`. | 6 |
| `connectors/kubernetes/pkg/contracts/` | ⚙️ **Generated.** Go structs from the JSON Schema. | 0 |
| `connectors/kubernetes/python_ref/` | Temporary Python implementation. **Deleted in Phase 6.** | 1 |
| `connectors/prometheus/` | Python. Range/instant queries, series and label discovery. | 1 |
| `connectors/loki/` | Python. LogQL queries and label discovery. | 2 |
| `connectors/alertmanager/` | Python. Active alerts, silences, grouping. | 1 |
| `connectors/gitlab/` | Python. Pipelines, jobs, merge requests, diffs. | 4 |
| `connectors/github/` | Python. Actions runs, pull requests, diffs. | 4 |
| `connectors/litmus/` | Python. Chaos experiment lifecycle and results. | 5 |
| **pkg/** | Go. Shared, importable Go libraries. One module per subdirectory. | 6 |
| `pkg/mcpserver/` | Shared MCP server package every Go connector builds on. | 6 |
| **cmd/** | Go binaries. | 6 |
| `cmd/pantheonctl/` | Operator CLI. | 6 |
| `cmd/collector/` | Signal-shipping sidecar. | 6 |
| **api/** | Python. FastAPI: `main.py`, `routers/`, `ws/`, `auth/`, `schemas/`. | 1–3 |
| **dashboard/** | TypeScript. Next.js 15 App Router — the only TS in the repo. | 4 |
| `dashboard/app/` | Routes: `investigations/`, `agents/`, `approvals/`, `settings/`. | 4 |
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
| `deploy/terraform/` | `modules/{network,k8s,postgres,redis,s3}`, `envs/{dev,prod}`. | 7 |
| `deploy/ansible/` | `playbooks/`, `roles/` for host-level provisioning. | 7 |
| `deploy/argocd/` | Argo CD Applications and projects. | 7 |
| `deploy/observability/` | Grafana dashboards, Prometheus rules, Alertmanager, OTel collector. | 7 |
| `deploy/security/` | Admission policies, sealed secrets, network policies. | 7 |
| `deploy/backup/` | Backup and restore jobs. | 7 |
| `deploy/scripts/` | `bootstrap-local`, `seed-db`, `smoke-test`, `teardown`. | 6 |
| **.github/** | `workflows/`, `ISSUE_TEMPLATE/`, `dependabot.yml`. | 7 |
| **docs/** | `architecture/`, `agents/`, `deployment/`, `adr/`, `diagrams/`. | 7 |
| `docs/adr/` | Architecture Decision Records, numbered `NNNN-title.md`. Active from Phase 0. | 0 |

---

## Where do I put X?

| I am adding… | It goes in | Also do |
|---|---|---|
| A new **agent** | `agents/<domain>/` — `agent.py`, `manifest.yaml`, `tools.py`, `prompts/`, `tests/` | Extend `agents/_base/base_agent.py`; register capabilities in `manifest.yaml`; add the codename to the agent table above |
| A new **connector** | `connectors/<name>/` — Python unless it needs a Go-only client library | Build on `connectors/_base/python/base_server.py`, or `pkg/mcpserver` for Go |
| A new **shared Go library** | `pkg/<name>/` with its own `go.mod` — never `connectors/_base/` | Add a `use` line to `go.work` |
| A new **contract / data shape** | `core/contracts/<name>.py` — **always here first** | Run `make codegen`; commit the regenerated output |
| A new **orchestrator stage** | `core/orchestrator/` | Zeus only — agents never orchestrate each other |
| A new **guardrail or policy** | `core/guardrails/` | Every write action must route through it |
| A new **HTTP endpoint** | `api/routers/<resource>.py` | Request/response bodies come from `core/contracts/`, never redefined |
| A new **WebSocket message** | `core/contracts/events.py` then `api/ws/stream.py` | Regenerate TS types |
| A new **dashboard route** | `dashboard/app/<route>/page.tsx` | Import types from `dashboard/types/generated/` only |
| A new **React component** | `dashboard/components/` | |
| A new **Helm template** | `deploy/helm/pantheon/templates/` | Add its values to all three `values*.yaml`; `helm lint` must pass |
| A new **Terraform module** | `deploy/terraform/modules/<name>/` | Wire it into `envs/dev` and `envs/prod`; `terraform fmt` must pass |
| A new **container image** | `deploy/docker/Dockerfile.<name>` | Add the service to the Compose stack |
| A new **CI check** | `.github/workflows/<name>.yml` | Trigger on PRs into `develop` |
| A new **simulator scenario** | `simulator/scenarios/<name>.yaml` | |
| A new **cross-cutting test** | `tests/{unit,integration,e2e}/` | Agent-specific tests belong in `agents/<domain>/tests/` |
| A new **Go module** | Its own directory with a `go.mod` under `github.com/simootaz/pantheon-aiops/<path>` | Add a `use` line to `go.work`. `make test-go` / `make lint-go` pick it up automatically |
| A new **Go package** in an existing module | `internal/` for module-private, `pkg/` for importable | Never `pkg/contracts/` — that is generated |
| A new **architecture decision** | `docs/adr/NNNN-<title>.md` | Number sequentially; link it from the CLAUDE.md changelog row |
| A **Go type mirroring a Python model** | ❌ **Nowhere.** | Add it to `core/contracts/` and generate it |
| Anything touching **object storage** | Any S3-compatible client against `S3_ENDPOINT_URL` | See [Standing decisions](#standing-decisions). Never hardcode an AWS endpoint or region |

---

## Generated files — never hand-edit

Three directories contain **only** machine-generated output. Editing them by hand
is a bug that CI will catch.

| Directory | Generated from | By |
|---|---|---|
| `core/contracts/export/` | `core/contracts/*.py` (Pydantic v2) | `codegen/export_schemas.py` |
| `connectors/kubernetes/pkg/contracts/` | `core/contracts/export/*.json` | `codegen/gen_go.sh` |
| `dashboard/types/generated/` | FastAPI OpenAPI schema | `codegen/gen_ts.sh` |

`codegen/verify.sh` regenerates everything into a temp directory and diffs it
against the committed output. **Any drift fails the build.** It runs in
pre-commit and in the `codegen-check` workflow.

To change any of these: edit `core/contracts/`, run `make codegen`, commit both
the contract change and the regenerated output together.

---

## Standing decisions

Cross-cutting rules that outlive any one branch. Each links to its ADR.

### Object storage is MinIO — never a cloud dependency

[ADR 0001](docs/adr/0001-object-storage-minio.md) · applies from Phase 6

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

| Target | Does |
|---|---|
| `make help` | List every target (default goal) |
| `make install` | Install Python, Go and dashboard dependencies |
| `make dev` | Run the API and worker locally with reload |
| `make sim` | Run a simulator scenario against the local stack |
| `make test` | Python test suite (`pytest`) |
| `make test-go` | `go build` + `go test` in every module listed in `go.work` |
| `make test-ts` | Dashboard test suite (`vitest`) |
| `make lint` | Lint and format-check Python (`ruff`) |
| `make lint-go` | `go vet` + `golangci-lint` in every module listed in `go.work` |
| `make lint-ts` | `biome` against the dashboard |
| `make typecheck` | `mypy --strict` over the Python tree |
| `make codegen` | Regenerate JSON Schema, Go structs and TS types |
| `make codegen-verify` | Fail if generated output has drifted |
| `make up` | Start the local Compose stack |
| `make down` | Stop the local Compose stack |
| `make clean` | Remove build artifacts and tooling caches |

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
could not. See [ROADMAP.md](ROADMAP.md#phase-0-branch-order).

| Order | Branch | Status |
|---|---|---|
| 1 | `feature/repo-skeleton` | ✅ merged |
| 2 | `feature/go-workspace` | ✅ merged *(was 3rd)* |
| 3 | `feature/python-tooling` | ⏳ next *(was 2nd)* |
| 4 | `feature/dashboard-scaffold` | ⏳ |
| 5 | `feature/codegen-pipeline` | ⏳ |
| 6 | `feature/deploy-skeleton` | ⏳ |
| 7 | `feature/ci-workflows` | ⏳ |
| 8 | `feature/docs-baseline` | ⏳ |

---

## Structure changelog

Every structural change gets a row. Date, what changed, which branch, which files.

| Date | Branch | Change |
|---|---|---|
| 2026-08-14 | `feature/go-base-relocation` | **Moved `connectors/_base/go/` → `pkg/mcpserver/`** (module `github.com/simootaz/pantheon-aiops/pkg/mcpserver`). `pkg/` is the idiomatic home for shared Go libraries, and the move removes the `_`-wildcard trap outright instead of documenting it. Updated `go.work`, `connectors/kubernetes/go.mod` (require + replace → `../../pkg/mcpserver`) and the three importing files; the import alias is no longer needed. `connectors/_base/python/` **stays** — its underscore is load-bearing for connector auto-discovery. Rewrote the CLAUDE.md Go section accordingly and corrected `connectors/_base/__init__.py`, which still claimed to host both languages. **Supersedes the wildcard guidance in the `feature/go-workspace` row below.** |
| 2026-08-14 | `feature/go-base-relocation` | **Definition of done corrected.** Dropped `go build ./...` — it cannot work from a non-module root. Replaced everywhere by the three commands that genuinely cover every module: `make lint-go`, `make test-go`, `go build github.com/simootaz/pantheon-aiops/...`. Branch 7 must use these in CI. |
| 2026-08-14 | `feature/go-workspace` | **Pending rename recorded, not yet applied.** `deploy/terraform/modules/s3/` → `deploy/terraform/modules/object-storage/`, made provider-shaped rather than AWS-specific. Scheduled for `feature/deploy-skeleton` (branch 6) per [ADR 0001](docs/adr/0001-object-storage-minio.md). On disk today the directory is still `modules/s3/`. |
| 2026-08-14 | `feature/go-workspace` | **Standing decision: object storage is MinIO.** Added `docs/adr/0001-object-storage-minio.md` and removed the now-redundant `docs/adr/.gitkeep`. Added a *Standing decisions* section here and an object-storage row to the *Where do I put X?* table. |
| 2026-08-14 | `feature/go-workspace` | **Branch order changed.** Branch 3 pulled ahead of branch 2 — the Python toolchain was not installed yet, so `feature/python-tooling` could not be verified while `feature/go-workspace` could. Recorded in ROADMAP.md and the phase roadmap above. |
| 2026-08-14 | `feature/go-workspace` | **Go workspace.** Added root `.golangci.yml` and four `go.mod` files (`connectors/_base/go`, `connectors/kubernetes`, `cmd/pantheonctl`, `cmd/collector`), all under `github.com/simootaz/pantheon-aiops`. Filled `go.work` with its `use` block. Replaced the Go placeholders with compiling stubs. Wired `make test-go` and `make lint-go` to iterate `go.work`. Documented that the repo root is not a module and that `_base/` is skipped by `...` wildcards. |
| 2026-08-14 | `feature/repo-skeleton` | **Initial tree.** Created `core/`, `agents/` (10 domains + `_base`), `connectors/` (7 + `_base`), `cmd/`, `api/`, `dashboard/`, `simulator/`, `codegen/`, `tests/`, `deploy/`, `.github/`, `docs/`. Added root `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `Makefile`, `pyproject.toml`, `go.work`, `.env.example`, `.gitignore`, `.dockerignore`, `.editorconfig`, `.pre-commit-config.yaml`. Every Python package has `__init__.py`; every intentionally empty directory has `.gitkeep`; the three generated directories have a `README.md` instead. |
