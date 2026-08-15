# Pantheon Roadmap

> **Phase: 0 - Scaffold & Tooling.** The full phase breakdown with exit criteria
> is written on branch `feature/docs-baseline`. The authoritative phase list
> currently lives in [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md#phase-roadmap).

## Phase 0 branch order

Phase 0 is delivered as eight feature branches. They were **reordered after
branch 1**: branch 3 was pulled ahead of branch 2.

**Reason:** the Python toolchain (`uv`, Python 3.12) was not yet installed, so
`feature/python-tooling` could not have its gate verified, while Go 1.23 was
already present and `feature/go-workspace` could be verified in full. Git Flow
is unaffected — the branches are independent.

| Order | Branch | Status |
|---|---|---|
| 1 | `feature/repo-skeleton` | ✅ merged |
| 2 | `feature/go-workspace` | ✅ merged *(was 3rd)* |
| — | `feature/go-base-relocation` | ✅ merged — unplanned; moved the shared Go library to `pkg/mcpserver` |
| 3 | `feature/python-tooling` | ✅ merged *(was 2nd)* |
| 4 | `feature/dashboard-scaffold` | ✅ merged |
| 5 | `feature/codegen-pipeline` | ✅ merged |
| — | `feature/api-minimal` | ✅ merged — unplanned; `create_app()` + `/health`, makes `make dev` live |
| 6 | `feature/deploy-skeleton` | ✅ merged |
| 7 | `feature/ci-workflows` | ✅ merged |
| 8 | `feature/docs-baseline` | ⏳ |

## Definition of done — Phase 0

On a fresh clone, all of the following must pass.

| Language | Commands |
|---|---|
| Python | `make install && make lint && make typecheck && make test` |
| Go | `make lint-go`, `make test-go`, `go build github.com/simootaz/pantheon-aiops/...` |
| TypeScript | `make lint-ts && make test-ts`, and `pnpm --dir dashboard build` |
| Codegen | `make codegen-verify` — must exit non-zero on planted drift, not merely exit zero on a clean tree |
| CI | `actionlint` and `zizmor` clean; `ci.yml` is the only required status and depends on every other check |
| Deploy | `helm lint deploy/helm/pantheon`, `terraform fmt -check`, `docker compose config` |
| Docs | docs/REPOSITORY_MAP.md accurately describes every directory that exists |

> **Note on the Go commands.** `go build ./...` is *not* used and must not be
> reintroduced. The repo root has no `go.mod`, so the pattern is invalid there,
> and adding a root module would not help — nested modules are pruned from a
> parent's package walk, so it would report success while building nothing. The
> three commands above cover all four modules and all eight packages.

## Delphi — the LLM gateway

Specified in [ADR 0004](docs/adr/0004-llm-provider-abstraction.md). Agents
declare `ModelRequirements`; Delphi resolves them to a model at call time.

| Phase | Delivers |
|---|---|
| **0** | Structure and contracts as documented stubs; `delphi:` Helm block; Ollama Compose service; `LLM_*` env vars |
| **2** | `gateway`, `resolver`, `catalog`, `chat_completions` adapter, `tracing`, `ResolutionRecord` persistence |
| **3** | Budget guard integrated with `core/guardrails/budget.py` — Delphi supplies price, guardrails decide |
| **4** | Settings surface: provider cards, tier pickers, per-agent overrides, **Test connection** probes, validation warnings |
| **5** | Remaining dialect adapters (`messages`, `generate_content`, `raw`) and `custom.py` hardening |

## Cerberus — the credential broker

Specified in [ADR 0005](docs/adr/0005-credential-brokering.md). Agents request
capabilities; they never hold credentials.

| Phase | Delivers |
|---|---|
| **0** | Structure, contracts, `redaction.py` implemented, all three safety guards |
| **3** | store, policy, audit, broker, lease, redemption; Approval Gate integration; rotation and revocation |
| **4** | Settings surface: credential inventory, grant table, permission modes, audit viewer |
| **5** | Rotation scheduling and the break-glass runbook |

## Agentic UI — AG-UI and A2UI

Specified in [ADR 0006](docs/adr/0006-agentic-ui-protocols.md). AG-UI is the
transport; A2UI is the payload for agent-generated UI.

| Phase | Delivers |
|---|---|
| **0** | Contracts, allowlist, structure, guards; `api/ws/` removed |
| **4** | AG-UI SSE endpoint and translator, A2UI surfaces for the Approval Gate and Cerberus, ArtifactRef resolution (server-side, same-investigation only), dashboard client and renderer |
| **5** | Replay from snapshot + patches |

## Deferred decisions

Things deliberately set to a scaffold-friendly value now, to be tightened later.

| Item | Now | Target | When |
|---|---|---|---|
| **Test coverage gate** | `--cov-fail-under=0` | `--cov-fail-under=80` | **Phase 1** — a scaffold has nothing to cover; gating it would be theatre |
| **Endpoint-surface TS types** | not generated | `codegen/gen_ts_api.sh` — paths, params, status codes from OpenAPI, additive beside the domain types | **Phase 1**, once `api/main.py` has real routes — see [ADR 0002](docs/adr/0002-codegen-from-json-schema.md) |
| **A2UI-over-AG-UI envelope** | `Custom` event named `a2ui`, isolated to `api/agui/a2ui_channel.py` | whatever the specs standardise | **Revisit each AG-UI/A2UI release.** No canonical envelope is documented; A2UI maps to A2A message Parts, and published AG-UI examples improvise. Cost of being wrong: one constant and one function |
| `Video` / `AudioPlayer` | excluded | admitted with the same `ArtifactRef` treatment as `Image` | when something actually needs them - the allowlist grows on demand, never speculatively |
| **A2UI v1.0** | pinned to v0.9.1 | v1.0 once released | v1.0 is a *release candidate*; it adds bidirectional typed function calls and single-message UI instantiation |
| **ag-ui SDK role mismatch** | pinned `>=0.1.20,<0.2` with the bug present | upstream fix | [ag-ui#1169](https://github.com/ag-ui-protocol/ag-ui/issues/1169) — `ReasoningMessageStartEvent.role` is `"assistant"` in Python and `"reasoning"` in TypeScript. Will bite when reasoning events are wired at Phase 4 |
| Redaction sink wiring | `redact()` implemented and tested | wired into logging, tracing and prompt assembly | Phase 2–3 |
| Generated credentials | dev/demo only, chart fails closed in production | supplied secrets everywhere, via Sealed Secrets | Phase 7 |
| Go event union | `Event interface{}` | hand-written typed accessors beside the generated file | Phase 6 — Go has no sum types; the generator will not invent one |
| `make sim` | stub, exits non-zero | wired | Phase 1, once `simulator.cli` exists |
| ~~`make dev`~~ | ✅ live — `uvicorn --factory`, `/health` serving | — | done on `feature/api-minimal` |
| ~~`pre-commit install`~~ | ✅ wired into `make install` | — | done on `feature/codegen-pipeline` |
| ~~Object storage~~ | ✅ MinIO everywhere, S3-compatible only; `modules/object-storage` renamed and applied | — | done on `feature/deploy-skeleton` |
| `unparam` / `nilnil` Go linters | disabled | enabled | Phase 6, once the Go connector is real |

<!-- TODO: Phase 0 - full roadmap with per-phase exit criteria on branch feature/docs-baseline -->
