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
| Contracts | 54 models, closed, exported to Go + TS |
| Codegen | Pydantic → JSON Schema → Go + TS, drift-verified |
| Deploy | Compose, Helm (lints + templates ×3), Terraform (validates), kustomize, Argo CD, observability, security, backup |
| CI | 9 workflows, SHA-pinned, one required check |
| Docs | 8 ADRs, repository map, architecture, this file |
| **Guards** | **78, each verified against a planted violation** |

Shipped as ten branches, two unplanned: `feature/go-base-relocation` and
`fix/generated-credential-policy`.

**Exit criteria — all met.** On a fresh clone: `make install && make lint &&
make typecheck && make test`, `make lint-go && make test-go`, `make lint-ts &&
make test-ts`, `make codegen-verify`, `helm lint` ×3, `terraform fmt -check`,
`docker compose config` ×3, `actionlint`, `zizmor`, and
`pnpm --dir dashboard build`.

---

## Phase 1 — Contracts & First Agent Path ✅

The first end-to-end slice: an alert produces a Finding.

**Complete.** The phase's criterion was "not complete until an alert actually
produces a Finding", and one does: `make test-flow-one` fires a scenario,
Alertmanager delivers the alert, Zeus opens an Investigation, dispatches Argus,
and a Verdict comes back citing the series that moved. A clean baseline opens
nothing.

What it does **not** mean: nothing reasons about a Finding, and nothing acts on
one. A Verdict aggregates and proposes no hypotheses — see Phase 2.

- ✅ `core/contracts/` filled out beyond the codegen-exercising minimum
- ✅ `core/registry/` — manifest discovery, capability matching
- ✅ `agents/_base/` — `BaseAgent`, tool binding, test fixtures
- ✅ **Argus** (anomaly detection) — the first real agent. Peer-relative robust
  z against per-metric thresholds and scale floors, every one measured rather
  than chosen and validated out-of-sample ([the derivation](docs/argus-threshold-matrix.md),
  [13 prediction records](docs/argus-predictions/)). `make test-argus` gates it
  both ways: three clean baseline runs produce zero Findings, all five scenarios
  are detected on the series that moved.
- ✅ Prometheus and Alertmanager connectors, read-only
- ✅ **Alerting rules and the trigger path** — one rule per scenario, wired
  through Alertmanager to `POST /webhooks/alertmanager`. Gated both directions
  per rule: the scenario fires its alert, a clean baseline fires none.
- ✅ `api/routers/` — investigations (list, fetch), the agent roster, and
  health's `/ready` and `/build-info`. The roster carries `implemented` per
  agent, read from the dispatcher's registry rather than the manifest: ten
  manifests validate and one agent runs, and a listing that hid that would be
  the most misleading thing this API could say.
- ✅ Simulator: metric, log and pipeline generation, five scenarios, `pantheon-sim`
- ✅ **Coverage floor raised.** Set from what the code measures rather than an
  aspiration: 95 aggregate, plus a per-module floor of 90 over the modules that
  actually branch (`tests/coverage_floor.py`). The aggregate alone is flattered
  because most statements are Pydantic field declarations covered by import.

## Phase 2 — Orchestrator & Investigation Flow 🚧 one capability short

**One of six.** Zeus runs flow 1 end to end, reaching all three agents. Delphi
has landed — resolution, capability probing, a fallback chain and a completion
cache — and `ResolutionRecord`s are written onto the Investigation.

Correlation groups findings by co-occurrence and `core/orchestrator/
hypotheses.py` ranks them, narrowly: a hypothesis is proposed only from a signal
whose metric **is** the thing the category describes. Errors, latency and CPU
corroborate and name nothing, so two of the five scenarios come back `UNKNOWN`
with their evidence attached — predicted as misses before the ranker was
written. `Verdict.dissent` records what the leading claim does not account for.

Per-category root-cause detail moved to **Phase 4**. Half its blocker lifted —
categories are produced now — and half did not: nothing computes a growth rate
or a time-to-full, so the detail would be a shape nobody fills.

**`make test-delphi` has now run against a real provider** — 5 passed,
2026-08-31. Until that moment every Delphi test used `RecordingProvider` or a
scripted fake, so "the adapter works" was asserted and "the provider answers"
was not. It is now observed: the configured provider answers a real prompt, a
wrong model id fails naming which one, the gateway reaches a model without
anyone naming one, JSON mode produces JSON, and the provider lists what it
serves.

- ✅ **Zeus**: router, classifier, planner, dispatcher, aggregator. An alert
  plans **two** steps — metrics and logs both cover it — and a human question
  plans one, to Hermes. The plan is built from what is implemented rather than
  what is rostered. No Temporal: a single step with no
  waits needs no durable execution, and `dispatcher.run_step` is the one
  function that would change — see ADR 0007 for what forces it.
- `core/memory/` — vector store, repository, cache
- 🚧 **Delphi**: gateway, resolver, catalog, `chat_completions` and tracing are
  implemented, unit-gated **and proven against a real provider**. What remains
  is the other dialect adapters (Phase 5). Nothing consults it yet - no agent
  reasons.
- **Lethe** and **Hermes**; Loki connector
- `ResolutionRecord` persistence
- Redaction wired into logging and tracing

## Phase 3 — Guardrails, Approvals & Write Actions ✅

- ✅ `core/guardrails/` — policy, approval gate, budget, executor. An approval
  binds to a **digest of the content the approver read**, not to an id, and the
  last policy rule is REQUIRE_APPROVAL so an unclassified operation gets a
  person rather than permission. Every receipt names the rule that decided it.
- ✅ **Cerberus** — store, policy, audit, broker, lease, redemption, rotation,
  revocation, break-glass. The vault has no plaintext getter; redemption is the
  only producer and checks the lease against the context it is used in. Every
  revocation kills the live leases too, or it takes effect in one TTL.
- ✅ **Aegis**; the first write tool behind approval. No agent may declare a
  mutating tool, which is safe by construction rather than by convention.
- ✅ Auth — bearer tokens, four roles, constant-time comparison. The approver's
  identity comes from the credential and no longer from the request body.
- ✅ **Tenant scoping.** `Investigation.tenant` and `Principal.tenant`, with the
  reads narrowed in the store rather than at each call site — one call site can
  forget it, and the filter has to run before the limit. Another tenant's run
  answers **404 rather than 403**, because existence is itself the disclosure.
  Cross-tenant is `@*` in the token table and is not inherited from ADMIN. The
  investigation reads are gated now: a scope an unauthenticated caller bypasses
  is a scope in name.

## Phase 4 — Delivery Flow ⬜ not started

- ✅ **A pull request reaches Aegis and a failed run reaches Hephaestus**, end
  to end: signed webhook, classifier, planner, params, dispatch.
- ✅ **Hephaestus** (flake vs unknown, from reruns at one commit) and ✅ **Themis**
  (merge frequency and review latency, both named for what they are rather than
  for the DORA metric they resemble); ✅ **GitHub connector** (read-only: Actions
  runs, jobs, pull requests, PR file patches) and ✅ **GitLab connector**.
  **GitHub is the one this deployment uses**; GitLab is built and kept, not
  invested in further.
  ✅ **Aegis reads a real pull request.** `github.file_at` reads the bytes at
  both shas rather than reconstructing from patches - GitHub omits `patch`
  above ~20k of diff, so a patch-based reviewer silently skips the large
  manifest changes most worth reviewing. Documents pair by identity, not
  position.
- ✅ **AG-UI endpoint and translator**; ✅ A2UI surfaces for the Approval Gate
  and Cerberus. The A2UI envelope remains a **documented guess** - no canonical
  AG-UI wrapper is specified - bounded to one function and one constant.
- `ArtifactRef` resolution — server-side, same-investigation only
- Dashboard: real investigation, agent, approval and settings views
- Delphi settings surface: provider cards, tier pickers, per-agent overrides,
  **Test connection** probes, validation warnings

## Phase 5 — Proactive Flow ⬜ not started

- **Moira**, **Mnemosyne**, **Clio**, **Eris**; Litmus connector
- Temporal workflows, activities, worker
- Replay from snapshot + ordered patches
- End-to-end tests against the simulator

## Phase 6 — Go Port & Platform Binaries ⬜ not started

- Kubernetes connector in Go; `connectors/kubernetes/python_ref/` **deleted**
- `pantheonctl`, `collector`
- Images built and published

## Phase 7 — Production Hardening ⬜ not started

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
| **`AgentBudget.max_tokens`** | ~~carried on every manifest, enforced nowhere~~ **enforced** in `core/guardrails/budget.py` against Delphi's token counts | — | **Done, 2026-08-28.** Metering lives in `BaseAgent.consult`, so an agent cannot exceed its budget by construction rather than by remembering to check; the ceiling is tested BEFORE the call, because a meter that only charges afterwards cannot stop anything. `test_nothing_reads_the_token_budget_yet` is **retired** and replaced by `test_only_the_runtime_reaches_a_gateway_directly`, which fails if a second, unmetered path to a gateway appears |
| **Argus peer-relative needs 12 peers** | measured; `peer_z` refuses below `MIN_PEERS = 12` | either a measured floor below 12, or peers pooled across a wider scope | **Before Argus ships against a real cluster.** Peer-relative removes the temporal path's period-estimation blocker - seasonality is common-mode across peers, so it cancels with no window and no period. It has a **replica-count blocker of its own**: real services commonly run 2-3 replicas, and a seeded sweep found 100% of three-peer subsets exceed \|z\| = 8 on clean data, worst case 9444, while the *best* three-peer subset came in at 24.92 - so a particular small group can look well behaved while every neighbouring choice is catastrophic. The two paths must be compared with both limitations stated, or peer-relative looks free when it is not. **Open question, not pursued:** whether peers can be pooled across a wider scope - all pods of similar workload, all nodes in a pool - to reach a usable count |
| **Chronos — deferred actions** | nothing; an agent that starts a long operation blocks past `max_seconds` and dies, or fires and forgets | `core/contracts/deferred.py`, a Temporal workflow per deferral, webhook completion with polling and a mandatory deadline behind it | **Phase 3 at the earliest**, after the Approval Gate — a deferred action is almost always a write, and the approval belongs to the moment of starting. Specified in [ADR 0007](docs/adr/0007-deferred-actions.md), status **Proposed**. The gap is concrete: `max_seconds` is 120 and a CI bisect takes 5-40 minutes, a chaos experiment up to 90. Waiting must not count against the budget or the same agent passes or fails depending on how busy an unrelated build queue was. First feature that genuinely requires Temporal rather than a queue. Arachne and Gaia both depend on this shape, so building either first means building a private version of it |
| **Host suspension breaks long gates** | known, undefended | a documented pre-flight, or a gate that detects and reports the gap | **Before anyone else runs these gates.** A measurement spanning tens of minutes can be interrupted by the host sleeping. Loki's ingester then ages its **own** entry out of its ring - `unhealthy instances: 127.0.0.1:9095` - and every push returns 500 for up to the 10m forget period before it re-registers; observed as a 21-minute outage mid-run. Nothing restarts and nothing is OOM-killed, so the container looks healthy throughout. `ScenarioRunner` now survives it and records `degraded` on the run, and `agents/anomaly/calibration.aggregate` refuses to compute a bound over runs whose condition is unrecorded - but neither prevents the interruption, and a reader of the numbers still needs to know it can happen |
| **Alert-gate stability, measured** | one green 8/8 run | run the gate **N times** and record the pass rate | **Before the first release**, not now — one run takes 48 minutes and Argus is the priority. A single green run is not a stability claim, and this gate has form: `noisy_neighbor` passed once at two evaluation intervals of headroom, on alignment luck, and `flaky_test_storm` failed at the identical figure. `MIN_HEADROOM_INTERVALS = 6` should make that unrepeatable; nothing has *shown* it. A rule that passes on alignment reads as green rather than as flake, so the pass rate is the only thing that distinguishes them |
| **`test_connector_path.py` in CI** | local only; no CI job starts the API | a CI job that brings up the API alongside Prometheus and runs `make test-connectors` | **Next CI branch.** The gate exists and passes locally but never executes on a runner, which is the shape this repository keeps finding. Deferred out of `fix/ci-green` deliberately: that branch's job was to make fifteen red runs green, and adding a job that has never run is how it would have stayed red |
| **Cross-attempt finding dedup** | ids are deterministic; only same-run duplicates are collapsed | a persistence upsert keyed on the Finding id | **Phase 2, with the persistence layer.** The id makes an identical claim *identifiable* across retries, which is the hard half. Actually merging two attempts needs a store to upsert into, and there is none - so today two attempts yield two objects sharing one id. `test_cross_attempt_dedup_is_not_claimed_to_exist` asserts the current behaviour, so building the upsert breaks it and forces this row and the `base_agent` docstring to be retired together |
| **Agent retry aggregate bound** | each attempt gets a fresh budget | `ScheduleToClose` plus a maximum attempt count on the activity | **Phase 2, with Temporal.** Seconds and tool calls are per-execution resources, so N retries × `max_tool_calls` is the real worst case. That ceiling belongs to the retry policy, which does not exist yet |
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
