# Pantheon Roadmap

Eight phases. Phase 0 builds the thing that makes Phases 1–7 safe to build.

| Phase | Name | Status |
|---|---|---|
| **0** | Scaffold & Tooling | ✅ **complete** |
| 1 | Contracts & First Agent Path | next |
| 2 | Orchestrator & Investigation Flow | |
| 3 | Guardrails, Approvals & Write Actions | |
| 4 | Delivery Flow | |
| 5 | Proactive Flow | |
| 6 | Go Port & Platform Binaries | |
| 7 | Production Hardening | |

---

## Phase 0 — Scaffold & Tooling ✅

Structure, tooling, contracts, codegen, deploy skeleton, CI, and the guards that
keep all of it honest. **No business logic.**

| Delivered | |
|---|---|
| Repository tree | every module documented, phase-marked |
| Python | uv, 3.12 pinned, ruff, mypy `--strict`, pytest |
| Go | workspace over 5 modules, golangci-lint, compiling stubs |
| TypeScript | Next.js 15, biome, vitest, AG-UI client, A2UI renderer |
| Contracts | 19 models, closed, exported to Go + TS |
| Codegen | Pydantic → JSON Schema → Go + TS, drift-verified |
| Deploy | Compose, Helm (lints + templates ×3), Terraform (validates), kustomize, Argo CD, observability, security, backup |
| CI | 9 workflows, SHA-pinned, one required check |
| Docs | 6 ADRs, repository map, architecture, this file |
| **Guards** | **78, each verified against a planted violation** |

Shipped as ten branches, two unplanned: `feature/go-base-relocation` and
`fix/generated-credential-policy`.

**Exit criteria — all met.** On a fresh clone: `make install && make lint &&
make typecheck && make test`, `make lint-go && make test-go`, `make lint-ts &&
make test-ts`, `make codegen-verify`, `helm lint` ×3, `terraform fmt -check`,
`docker compose config` ×3, `actionlint`, `zizmor`, and
`pnpm --dir dashboard build`.

---

## Phase 1 — Contracts & First Agent Path

The first end-to-end slice: an alert produces a Finding.

- ✅ `core/contracts/` filled out beyond the codegen-exercising minimum
- `core/registry/` — manifest discovery, capability matching
- `agents/_base/` — `BaseAgent`, tool binding, test fixtures
- **Argus** (anomaly detection) — the first real agent
- Prometheus and Alertmanager connectors
- `api/routers/` — investigations, agents, health
- ✅ Simulator: metric, log and pipeline generation, five scenarios, `pantheon-sim`
- ✅ **Coverage floor raised.** Set from what the code measures rather than an
  aspiration: 95 aggregate, plus a per-module floor of 90 over the modules that
  actually branch (`tests/coverage_floor.py`). The aggregate alone is flattered
  because most statements are Pydantic field declarations covered by import.

## Phase 2 — Orchestrator & Investigation Flow

- **Zeus**: router, classifier, planner, dispatcher, aggregator
- `core/memory/` — vector store, repository, cache
- **Delphi** implemented: gateway, resolver, catalog, `chat_completions`, tracing
- **Lethe** and **Hermes**; Loki connector
- `ResolutionRecord` persistence
- Redaction wired into logging and tracing

## Phase 3 — Guardrails, Approvals & Write Actions

- `core/guardrails/` — policy, approval gate, budget
- **Cerberus** implemented: store, policy, audit, broker, lease, redemption,
  rotation, revocation, break-glass
- **Aegis**; write tools behind approval
- Auth and tenant scoping

## Phase 4 — Delivery Flow

- **Hephaestus** and **Themis**; GitLab and GitHub connectors
- **AG-UI endpoint and translator**; A2UI surfaces for the Approval Gate and
  Cerberus
- `ArtifactRef` resolution — server-side, same-investigation only
- Dashboard: real investigation, agent, approval and settings views
- Delphi settings surface: provider cards, tier pickers, per-agent overrides,
  **Test connection** probes, validation warnings

## Phase 5 — Proactive Flow

- **Moira**, **Mnemosyne**, **Clio**, **Eris**; Litmus connector
- Temporal workflows, activities, worker
- Replay from snapshot + ordered patches
- End-to-end tests against the simulator

## Phase 6 — Go Port & Platform Binaries

- Kubernetes connector in Go; `connectors/kubernetes/python_ref/` **deleted**
- `pantheonctl`, `collector`
- Images built and published

## Phase 7 — Production Hardening

- Terraform resources, Argo CD, Ansible
- Grafana dashboards, Prometheus rules, OTel pipeline
- Admission policies, sealed secrets, network policies
- Velero and Postgres backups against object storage
- `build-push.yml` and `release.yml` made real

---

## Deferred decisions

Everything deliberately set to a scaffold-friendly value, with the trigger for
changing it. Nothing here is forgotten; each row is a debt with a due date.

| Item | Now | Target | When |
|---|---|---|---|
| `pre-commit install` | wired into `make install` | — | ✅ done once `verify.sh` became real |
| `make dev` / `make sim` | wired | — | ✅ done at Phase 1, once `api.main:app` and `simulator.cli` became real |
| **Simulator compression ceiling** | ~`tick_seconds / 0.29` — a tick costs two HTTP round trips whatever it covers | batched or in-process ingestion if a scenario ever needs more | **When a scenario cannot be expressed within it.** Not a defect: `RunReport.achieved_speed` and `kept_up` report the shortfall instead of hiding it, and the gate asserts on the speed actually delivered. Raising `tick_seconds` buys compression linearly and costs phase-boundary resolution |
| **`gen_ts_api.sh`** | does not exist | additive generator for endpoint-surface types (paths, params, status codes) from OpenAPI | **Phase 1**, alongside real routes. Separate from `gen_ts.sh`: domain types come from JSON Schema so they are not shaped by routing accidents |
| **`remote_write` for metrics** | pushgateway + compressed time | Prometheus `remote_write` with explicit timestamps | **Phase 6, when Moira lands.** Pushgateway discards timestamps by design, so a baseline only exists in elapsed time. Capacity forecasting needs ~30 days of history to predict the next 30, and no scrape interval can compress that — a 30-day window at 1s scrape is 2.6M samples per series. This becomes necessary, not optional |
| **Counter rates scale with `speed`** | `rate()` returns the simulated rate × the compression factor | explicit timestamps remove the distortion entirely | **Same trigger as the row above.** Counters accumulate simulated increments while Prometheus scrapes in wall time. Correct — the alternative loses the simulated totals — but it means absolute counter thresholds only hold at `speed=1`. Ratios and within-run comparisons are unaffected, because the factor cancels; the gate uses those deliberately. Documented at the top of `simulator/metrics_generator.py` |
| **A2UI envelope** | `Custom` event named `a2ui`, isolated to `api/agui/a2ui_channel.py` | whatever the specs standardise | **Revisit each AG-UI/A2UI release.** No canonical envelope is documented; cost of being wrong is one constant and one function |
| **A2UI v1.0** | pinned to v0.9.1 | v1.0 | once released — it is a *release candidate*, and the spec recommends 0.9.1 for production |
| **ag-ui#1169** | pinned `>=0.1.20,<0.2` with the bug present | upstream fix | `ReasoningMessageStartEvent.role` is `"assistant"` in Python and `"reasoning"` in TypeScript. **Will bite when reasoning events are wired at Phase 4** |
| `unparam` / `nilnil` Go linters | disabled | enabled | **Phase 6** — every stub returns a constant, so they would fire on all of them |
| `Video` / `AudioPlayer` | excluded from the allowlist | admitted with the same `ArtifactRef` treatment as `Image` | when something needs them; the allowlist grows on demand, never speculatively |
| Redaction sink wiring | `redact()` implemented and tested | wired into logging, tracing, prompt assembly | Phase 2–3 |
| Generated credentials | dev/demo only; chart fails closed in production | supplied secrets everywhere via Sealed Secrets | Phase 7 |
| Go event union | flattened by the generator | a tagged union | Phase 6, if the Go connector needs to consume events |

## Definition of done — Phase 0

| Language | Commands |
|---|---|
| Python | `make install && make lint && make typecheck && make test` |
| Go | `make lint-go`, `make test-go`, `go build github.com/simootaz/pantheon-aiops/...` |
| TypeScript | `make lint-ts`, `make test-ts`, `pnpm --dir dashboard build` |
| Deploy | `helm lint` ×3, `helm template` ×3, `terraform fmt -check -recursive`, `terraform validate`, `docker compose config` ×3 |
| CI | `actionlint`, `zizmor --persona pedantic` |
| Codegen | `make codegen-verify` — **must exit non-zero on planted drift**, not merely zero on a clean tree |
| Guards | every guard verified against a planted violation, both directions |
| Docs | `docs/REPOSITORY_MAP.md` accurately describes every directory that exists |

> **Note on the Go commands.** `go build ./...` is not used and must not be
> reintroduced. The repo root has no `go.mod`, so the pattern is invalid there,
> and adding a root module would not help — nested modules are pruned from a
> parent's package walk, so it would report success while building nothing.

## Phase 0 branch order

Delivered as ten branches; two were unplanned, and the order changed once.

| # | Branch | Note |
|---|---|---|
| 1 | `feature/repo-skeleton` | |
| 2 | `feature/go-workspace` | pulled ahead — the Python toolchain was not installed yet, so its gate could not be verified |
| — | `feature/go-base-relocation` | unplanned — moved the shared Go library to `pkg/mcpserver` |
| 3 | `feature/python-tooling` | |
| 4 | `feature/codegen-pipeline` | |
| 5 | `feature/api-minimal` | |
| 6 | `feature/repo-map-neutralization` | + history rewrite |
| 7 | `feature/neutrality-guard-narrowing` | + ADR 0004 |
| 8 | `feature/deploy-skeleton` | |
| — | `fix/generated-credential-policy` | unplanned — the chart would have rotated production credentials under GitOps |
| 9 | `feature/ci-workflows` | |
| 10 | `feature/cerberus-credential-brokering` | |
| 11 | `feature/agentic-ui-protocols` | |
| 12 | `feature/artifact-backed-media` | |
| 13 | `feature/dashboard-scaffold` | |
| 14 | `feature/docs-baseline` | this one |
