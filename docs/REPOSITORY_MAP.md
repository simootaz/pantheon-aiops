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
| `core/llm/provider.py` | The adapter Protocol every dialect implements, plus `Completion` and a recording fake. `stream` and `probe` are deliberately absent until something calls them. | 2 |
| `core/llm/catalog.py` | Configured providers and models. A configured model is described as **unprobed** - zero context, baseline capabilities - because configured is not observed. | 2 |
| `core/llm/resolver.py` | The four-step cascade. A binding that cannot satisfy the requirements is skipped; an explicit override that cannot is an **error**, never a downgrade. | 2 |
| `core/llm/providers/chat_completions.py` | The reference dialect adapter. Refuses to guess: no `choices` raises rather than returning `""`, because an empty completion and a model that said nothing are different facts. | 2 |
| `core/llm/fallback.py` | The chain Delphi tries next. **Never widens the search** - every candidate satisfies the SAME requirements, because a chain that relaxed a declared capability under load produces its worst output exactly when the system is struggling, and nothing in the result would say so. Extracted from the gateway so that rule is reviewable rather than buried in a class's fifth responsibility. | 2 |
| `core/llm/probe.py` | Models describe themselves **by being asked to perform**. No hardcoded table: one is stale in weeks and describes the marketing, not the deployment. Probes reachability, latency and `JSON_MODE`; `TOOL_USE` and `VISION` are recorded as **unprobed** because `Provider.complete` has nowhere to put a tool schema or an image - and unprobed is not absent. | 2 |
| `core/llm/capability_matrix.py` | Observations, not facts. Keeps `present` and `absent` apart so a third state - **not checked** - survives; conflating those two is what left Hermes permanently unresolvable. Staleness is answered on read, so it cannot depend on whether a sweep ran. | 2 |
| `core/llm/gateway.py` | `consult()`. The fallback chain never widens the search - relaxing a declared capability under load produces the worst output exactly when the system is struggling. | 2 |
| `core/llm/tracing.py` | A span per call carrying a prompt **digest**, not the text: redaction removes the secrets Cerberus knows about and cannot remove the ones nobody registered. | 2 |
| `tests/integration/test_delphi_live.py` | Delphi against whatever provider is configured. **Skips** without a key rather than failing - a red gate meaning "you did not sign up for a service" trains people to ignore red gates. | 2 |
| `tests/unit/test_llm_gateway.py` | The adapter, the chain, the cost stop and the span - all offline behind an injected transport. | 2 |
| `tests/unit/test_llm_resolution.py` | The cascade rung by rung, both refusals, and the rejection record that explains why. | 2 |
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

That last clause was false for fifteen runs. `action-setup` reads the
**repository root** `package.json` by default, and this repo has none, so every
dashboard job failed while three files said the mechanism worked. It needs
`package_json_file: dashboard/package.json` stated explicitly, and
`tests/unit/test_ci_is_runnable.py` now asserts it.

pnpm **settings** live in `dashboard/pnpm-workspace.yaml`, not in a `pnpm` key
in `package.json` - pnpm 10+ ignores that key silently. The `overrides` there
pull `sharp` and `postcss` above the versions `next` resolves transitively,
which `trivy fs` reports as HIGH.

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
├── .gitattributes          LF everywhere, as a repo property not a local setting
├── LICENSE                 Apache 2.0
├── .pre-commit-config.yaml ruff, ruff-format, mypy, gitleaks, codegen drift
├── .trivyignore            misconfiguration suppressions, each with its reason
├── .gitleaks.toml          secret-scanning rules for this repository
└── docs/REPOSITORY_MAP.md  ★ this file — the canonical map
```

| Directory | Purpose | Phase |
|---|---|---|
| **core/** | Python. Everything that is not an agent and not a connector. | 1–5 |
| `core/contracts/` | ★ **Source of truth.** Pydantic v2 models for every cross-language shape, with validators. | 1 |
| `core/contracts/root_cause.py` | `RootCauseCategory` — the closed vocabulary agents, verdicts **and scenario ground truth** all draw from. | 1 |
| `core/contracts/export/` | ⚙️ **Generated.** JSON Schema emitted from the models. | 0 |
| `core/contracts/verdict.py` → `Dissent` | Evidence the leading claim does not account for, **attributed to the agents that reported it**. Nothing votes here, so "the agents disagreed" cannot be read off anything they said - what is observable is that the run produced more than one candidate. A reader told "memory leak, 0.65" has no way to know two of five findings pointed at disk, and that omission is the difference between a conclusion and a summary of the majority. **A tie records none**: two equals are a run that reached no conclusion, not a majority with objectors, and the contract refuses dissent at confidence 0.0. | 2 |
| `api/routers/webhooks.py` → `POST /webhooks/github` | Verifies GitHub's HMAC-SHA256 over the **raw body**, then parses. Taking a parsed `dict` and re-serialising it produces different bytes - different whitespace, different key order - so that version rejects every genuine delivery; the worse version accepts a body it never verified. **Order matters**: an unsigned malformed body is a 401, not a 400, which is the observable proof the parser never saw it. `GITHUB_WEBHOOK_SECRET` is **required in production**, the same split as GitLab - a token reaches out, a secret guards something reaching in. An event nobody acts on is still 202: a 400 would make a green delivery log go red for working correctly. | 4 |
| `core/orchestrator/classifier.py` → `subject_of` | What a trigger is **about**, as parameters an agent can act on. Empty for an alert - Argus and Lethe take the window, which is already on the context - and populated for a pull request or a failed CI run, because Aegis and Hephaestus are pointed at one thing and cannot find it from a time range. Extraction lives beside the classification rather than in the dispatcher: **two readers of one payload is one that can disagree with the other**. A green workflow run routes nowhere; GitHub sends `workflow_run` for every completion, and investigating every green build is how a system teaches people to ignore it. | 4 |
| `core/orchestrator/hypotheses.py` | Ranks correlated Findings into candidate causes, and **refuses to name what it cannot**. A signal that *names* a cause and one that is a symptom are different: `pantheon_pod_memory_working_set_bytes` **is** resident memory, so growth naming a leak is semantics, not a heuristic. Errors, latency and CPU corroborate and propose nothing - so `bad_deploy_5xx` and `noisy_neighbor` come back **UNKNOWN with their evidence attached**, because nothing reports deployments and nothing knows which pods share a node. Both were committed as predicted misses *before* the module existed: the ground truth is in this repository and a mapping that named all five would have been fitted to it. | 2 |
| `core/orchestrator/correlation.py` | Groups Findings that describe **one resource in one window** - a fact, checkable from the Findings themselves. It does **not** claim they share a cause: "the memory anomaly caused the OOM" and the reverse are both consistent with co-occurrence, and the scenarios carry ground truth for that field, so an invented ordering would be scored as though it were reasoning. Subjects must match exactly - `ResourceRef` has no parent link, so a pod and its service cannot be joined without topology. | 2 |
| `core/orchestrator/` | **Zeus.** `router`, `classifier`, `planner`, `dispatcher`, `aggregator`. | 2 |
| `core/registry/` | Agent manifest discovery and capability matching. | 1 |
| `core/guardrails/` | `policy`, `approval_gate`, `budget` — every write action passes here. Cerberus reuses this Approval Gate; there is no second inbox. | 3 |
| **core/cerberus/** | **Cerberus** — the credential broker. Three heads: `store/` (custody), `policy/` (decisions), `audit/` (memory), plus `broker`, `lease`, `redemption`, `redaction`. Not an agent. | 3 |
| `core/cerberus/store/` | ⛔ **Plaintext.** Agents must not import anything here. All five modules are live. | 3 |
| `core/cerberus/redemption.py` | ⛔ **The only producer of plaintext.** Connector-side only. | 3 |
| `core/workflows/` | Temporal `workflow`, `activities`, `worker` for long-running investigations. | 5 |
| `core/memory/` | `cache` (live) and `vector_store` (deferred). **`repository.py` was deleted**: it duplicated `core/store/`, which already persists Investigations and is gated. See [ADR 0008](adr/0008-memory-layer-scope.md). | 2 |
| `core/llm/` | **Delphi** — the LLM gateway. Resolution cascade, capability probing, dialect adapters, shared `prompts/`. Not an agent. Credentials come from Cerberus. | 2 |
| `core/llm/providers/` | Dialect adapters, named by wire format not vendor: `chat_completions` ★ is live; `messages`, `generate_content` and `raw` are Phase 5 and refused at the door rather than stored. `custom.py` is not a dialect - the settings-defined provider it describes **landed in `api/routers/providers.py`**. | 2 |
| `core/observability/` | OTel setup, platform metrics, structured logging. | 1 |
| **agents/** | Python. Ten domain agents, one folder each. | 1–5 |
| `agents/_base/` | `base_agent`, `tool_binding`, `testing` — shared agent scaffolding. | 1 |
| `agents/<domain>/` | One agent: `agent.py`, `manifest.yaml`, `tools.py`, `prompts/`, `tests/`. | varies |
| **connectors/** | Polyglot. Each connector is a separate process speaking MCP. | 1–6 |
| `connectors/_base/python/` | `base_server.py` — base MCP server for Python connectors. The `_` keeps it out of connector auto-discovery. | 1 |
| `connectors/kubernetes/` | **Go.** `cmd/server/`, `internal/{tools,readonly,write,client}/`. | 6 |
| `connectors/kubernetes/python_ref/` | Temporary Python implementation. **Deleted in Phase 6.** | 1 |
| `connectors/github/` | Python. Actions runs, jobs, pull requests and PR file patches - **read-only**, path-allowlisted, so merge, branch-delete and workflow-rerun are unreachable. `/actions/runs/7` reads and `/actions/runs/7/rerun` spends money, and only an exact match tells them apart. **A rate limit is not an authentication failure**: GitHub answers 403 for both, one is fixed by waiting and one by fixing a token, so `X-RateLimit-Remaining` is read and the reset named. The API version is **pinned** - unset, a response shape can change under a running deployment. `owner/repo` stays two segments, the opposite of GitLab's encoded one. | 4 | `file_at` reads one file at one commit, which is what makes a real before/after pair possible.
| `connectors/gitlab/` | Python. Pipelines, jobs, merge requests and MR diffs - **read-only**, path-allowlisted, so the pipeline-trigger, branch-delete and merge endpoints are unreachable. `/pipeline` and `/pipelines/7` are one character apart and the allowlist is what tells them apart. The **token travels in a `PRIVATE-TOKEN` header**, never `?private_token=`: a credential in a query string is in the proxy's access log and in the history of whoever pasted the URL. A project reference is **validated and encoded before substitution**, `..` refused separately as defence in depth. A 401 is reported as a rejected credential, not as an empty result. | 4 |
| `connectors/prometheus/` | Python. Range/instant queries, series and label discovery. | 1 |
| `agents/nl_query/agent.py` | **Hermes.** A question in, a connector query and a checkable answer out. The first agent to consult Delphi, so the first place ADR 0004 is exercised end to end. The model proposes a tool and a query; **Hermes supplies the time range and validates the tool before calling it**, and an empty result is reported without consulting a model at all - handing one an absence is how "no error rows" becomes "the service is healthy". | 2 |
| `core/guardrails/approval_gate.py` | An Action waits here for a person. An approval is for **the content the approver read**, not for an id - a digest of the decision-relevant fields, so proposing a dry run, getting it approved and flipping `dry_run` is refused. The timeout **fails closed**, and an approval decays to EXPIRED while a rejection does not: authority granted at noon should not still be spendable at eight. The proposer cannot approve. | 3 |
| `core/cerberus/lease.py` | Short-lived permission bound to **one connector, one run, and one live grant** - which is what makes a leaked lease worthless. It cannot widen what was granted, cannot outlive it, and a grant scoped to one investigation does not carry into another. Nothing here can produce a credential; a lease is permission, and `redemption.py` is the only module that yields plaintext. | 3 |
| `agents/manifest_review/sources.py` | Turns a pull request's files into the before/after pairs Aegis reviews - by **fetching the bytes at both shas**, never by applying the patch. GitHub omits `patch` entirely above ~20k of diff, so a patch-based reviewer silently skips the large manifest changes most worth reviewing and reports a clean run. Documents are paired **by identity (kind, name, namespace), not by position**: pairing first-with-first reports a Deployment replaced by a Service every time somebody sorts a file. `apiVersion` is deliberately not part of the key, so an `apps/v1beta1` → `apps/v1` migration is one object moving. `safe_load_all`, never `load_all` - these documents come from whoever opened the PR. | 4 |
| `agents/ci_triage/triage.py` | **A flake has a definition, not a heuristic**: the same job at the same commit finishing two different ways is non-determinism, read off two recorded outcomes rather than inferred. Every other available signal is a guess - a name containing "flaky", a different failing step, how often it fails. One observation is **UNKNOWN**, which is most CI failures: an agent labelling every first failure would be right about half of them and trusted for neither. `cancelled` is not a failure (somebody pushed again) and not a pass (or every interrupted failure reads as flaky). | 4 |
| `agents/ci_triage/agent.py` | **Hephaestus.** Reads every run at the commit, not only the one that fired - GitHub records a rerun as a separate run at the same `head_sha`, so reading one makes every flake look like a plain failure. Declares three GitHub tools and calls three; `github.diff` and `correlate_with_change` are **gone rather than unimplemented**, because linking a failure to its change needs the parent commit's runs and the commits API is not reachable. A declared capability nothing can perform reads as one that works. | 4 |
| `agents/manifest_review/diff.py` | **One set difference**: `protections(before) - protections(after)`. Nothing scans a manifest for bad patterns, and that is the design rather than a detail - a reviewer matching on the AFTER state reports on the workload, so every review of an old Deployment says "no liveness probe", true and unrelated to the diff. A protection missing from both sides never appears. Additions like `privileged: true` are modelled as the removal of the protection they cancel, so they travel the same mechanism instead of a second one that would have to agree with it. | 3 |
| `agents/manifest_review/agent.py` | **Aegis.** Reports what a change takes away and how far the object reaches; it does **not** decide whether the change is wrong - deleting a readiness probe is right for a batch worker, and nothing in a manifest says which case this is. No risk score: a number would be fitted and read as calibrated. Severity comes from reach alone, which is categorical and from the Kubernetes object model. The diff is **supplied on `ctx.params`, not fetched** - the gitlab and github connectors are Phase 4 - and a missing one degrades rather than reviewing as clean. Declares **no tools**. | 3 | **Reads a pull request now**, or takes the manifests handed to it - both are legitimate, and a supplied change costs no requests. The base sha is fetched, not derived: the `files` listing names what changed and carries neither sha. A file's `status` decides which sides exist, so an `added` file is never fetched at the base (a 404 that would abort a review over a file that is fine) and a **rename reads `previous_filename`** at the base. Over `MAX_FILES` it degrades rather than reviewing a prefix - each file costs two requests, and a silent prefix reports a clean change for every file it never opened.
| `core/contracts/credentials.py` → `ConnectionDescriptor`, `RotationRecord` | The wire form of how a credential travels, so a settings UI can say "this one arrives as a file called kubeconfig" without importing `core.cerberus.store` - the package it is forbidden to reach. **No field holds a value**; `channel` is a variable name, a header name or a filename. `RotationRecord` is **derived from the audit trail, never stored beside it**: the trail is already append-only and already records every rotation, and a second store is a second thing to keep in sync - the one that drifts being the one somebody consults to answer "when was this last rotated". | 3 |
| `core/cerberus/store/kinds.py` | **How a credential travels is a security property**, not a formatting detail: a kubeconfig on a command line is in `ps` output for every process on the box, a token in a query string is in the proxy's access log. The handoff is declared per type and `ARGUMENT` is refused outright. A CR or LF in an HTTP credential **splits the request carrying it** - header injection, reachable by anyone who can set a credential, one line to check. Validation is shape only and runs at `put`, because a malformed credential found at 03:00 presents as the connector being broken. | 3 |
| `core/cerberus/store/rotation.py` | **Which version a lease gets is decided by when the lease was issued** - not by a flag, which would put the choice in the hands of whoever calls `redeem` and hand a new secret to an old lease mid-rotation. The retention window is **computed, not configured**: at rotation the latest expiry among live leases is already known, and that is exactly when the old value stops being reachable. The boundary is inclusive - a lease minted in the same tick is a lease in flight. `purge` reclaims memory and changes no answer. | 3 |
| `api/main.py` → lifespan, `_correlate` | The lifespan gives the pools back: a lazily created pool held for the life of the process leaks one per reload until Postgres refuses connections, and that presents as **the database being down**. Each store closes in its own `try`, because a shutdown path that stops at the first error is one that does not run. A `RequestValidationError` handler **redacts the echoed input** - FastAPI hands the offending body back so a caller can fix it, which is right and is also how a credential POSTed into a malformed request returns in the error. Redacted, not omitted: a 422 nobody can act on is a 422 people stop reading. | 3 |
| `core/contracts/events.py` → `ReplayCursor` | The bus is in memory, so its guarantee is **AT_MOST_ONCE and says so** - the only thing worse than a bus that loses events is one that loses them while something downstream believes it does not. What makes that workable is that the loss is detectable at the READER: sequences are monotonic per investigation, so a consumer seeing 5 after 3 knows it missed 4. `gaps` carries the **size**, because missing one event and missing forty are different situations. `sequence` is `None` until something is seen - not 0, which is a real first event. A late arrival never rewinds: that turns one late event into a storm of duplicates. | 3 |
| `api/auth/dependencies.py` | **Identity comes from the credential, never from the payload.** `POST /approvals/{id}` took the approver's name from the request BODY, and the gate then checked that the approver was not the proposer - against a string the caller had just chosen. Bearer tokens compared with `hmac.compare_digest`, because a `==` on a secret returns as soon as two bytes differ and turns guessing into a per-character search. An empty table authenticates **nobody**, which is the opposite of the bug this shape invites; production refuses to start without one. **ADMIN is not a wildcard** - the set of people who can approve must be the set of people listed as approvers. | 3 | **Tenant scoping**: a `Principal` carries its tenant and reads are narrowed to it. Cross-tenant is spelled `@*` in the token table and is **not** inherited from ADMIN - implicit inheritance means the set of people who can read every tenant is not the set configured to. Another tenant's investigation answers **404, not 403**: a 403 confirms it exists, and for isolation existence is itself the disclosure.
| `core/cerberus/redaction.py` → `REDEEMED` | The Phase 3 TODO asked for redaction literals to be **sourced from the Cerberus store**. That is impossible, and why is the point: the vault has no plaintext getter, and a redactor that could read it would be a second producer of secrets. The only moment a credential is in the clear is redemption, so that is where it registers. A secret shorter than 8 characters is **refused loudly** - a short literal is a substring of everything, and registering one would replace that text throughout every log line in the process, which reads as a formatter bug. | 3 |
| `core/cerberus/broker.py` | **The only Cerberus module an agent may touch.** An AccessRequest in, a Lease out - and no path from here to a credential, asserted on the surface rather than left to convention. An unconsidered request is **parked and visible**: raising and forgetting would leave the sentence that *is* the decision ("argus wants the production database, to test whether connection saturation explains the latency") in an exception message and nowhere else. The credential gate is the Grant, not `guardrails/approval_gate.py`, which binds to a digest of an Action's content - an AccessRequest has no target and no parameters, so routing through it would mean a digest over fields that do not exist. | 3 |
| `core/cerberus/policy/` | `scope` · `modes` · `grants` · `defaults` · `revocation`. **Unset on a grant is "any"; unset on a request is "unknown"** - so a staging grant does not answer a request that never said where it was pointing. Any DENY beats any ALLOW, however narrow, because the alternative makes revocation a search problem. A lapsed grant answers ASK and not DENY: "renew it" and "no, and here is why" are opposite conversations. An unnamed environment is **production**. | 3 |
| `core/cerberus/policy/revocation.py` | Three scopes, and **every one kills the leases too**. Revoking a grant stops the *next* lease and nothing else - redemption checks the lease, deliberately, so producing a credential does not depend on a policy lookup being reachable. A revocation that touched only grants would take effect in one TTL, which is defensible for one grant and indefensible for break-glass, used precisely when five minutes is the whole problem. Reports grants and leases separately: "revoked 3" cannot answer the question anybody asks. | 3 |
| `core/cerberus/store/vault.py` | Envelope-encrypted credentials, and **no plaintext getter** - `get()` returns a `Sealed` record. A convenience method here would make this a second producer of secrets and put a decrypt one import away from an agent, which is the exact boundary `test_credential_safety.py` enforces. Retaining nothing is asserted against the instance's own state, not against its method names: a stashed value needs no getter to leak. Rotation **rewraps** the data keys and never touches the ciphertext, all-or-nothing. | 3 |
| `core/cerberus/redemption.py` | **The only producer of plaintext**, connector-side only. Checks the lease against the context it is being used in - the connector, the run, the clock - rather than against itself, because reading them off the lease would compare it with itself and check nothing. Refusals are **recorded before they are raised**: "a connector tried to redeem a lease it did not hold" living only in an exception message is precisely the event somebody wants to find later. | 3 |
| `core/cerberus/audit/` | The append-only trail, **enforced rather than documented**: no `delete`, `entries()` hands back a copy, and `AuditEntry` is frozen - it said "immutable" for two phases while assignment worked fine. Records every Action outcome including the refusals, because "nobody proposed this" and "policy said no" are different facts and only the trail separates them. | 3 |
| `core/guardrails/executor.py` | **The only path from a proposed Action to a system that changes.** Policy decides, an approval is re-validated against the Action *as it is now*, and a receipt is written whatever happens - an Action that was refused and one nobody tried look identical without it. Agents never execute: no manifest may declare a mutating tool, which is safe by construction rather than by convention. | 3 | Every receipt names the **rule that decided it** - required and non-empty, so a receipt that cannot answer "why did this run" is unconstructible. It said what happened and never what let it: for a refusal the rule lived in an exception message, for a success nowhere at all.
| `core/guardrails/policy.py` | Whether an Action may run, needs a human, or must not run. **The last rule is REQUIRE_APPROVAL**, so an operation nobody classified gets an approver rather than permission - the other ordering makes every capability added after the file was written allowed until someone notices. A cluster-wide change in production is a **deny**, not an escalation, because break-glass is a stub and a gate nobody can pass presents as a stuck approval. Every ruling names its rule: at 03:00 the question is *which* no. | 3 |
| `core/observability/logging.py` | Structured JSON logs, correlated by investigation, with **every configured secret registered as a literal** so a credential in a sentence is scrubbed - pattern rules only catch secret-*shaped* mappings, and a sentence has no keys. A filter on the handler rather than a formatter, so a second handler added later cannot emit unredacted lines. `redaction.py` had been implemented and wired to nothing since Phase 0. | 1 |
| `core/contracts/investigation.py` → `AgentAccounting` | What each agent consumed, **beside what it was allowed**. "spent 16000 tokens" cannot answer the question anybody asks - 16000 of 16384 and 16000 of 200000 are different runs and the same number. All three ceilings, because a run stopped by its budget and one stopped by its clock look identical from outside and are fixed differently. | 2 |
| `core/guardrails/budget.py` | **`AgentBudget.max_tokens`, enforced.** The ceiling is checked *before* a call, using the worst case rather than an expectation - a meter that only charges afterwards cannot stop anything, and assuming a completion will be shorter than allowed is an assumption about output made before any exists. Running out **stops** the run; it does not switch to a cheaper model. | 3 |
| `core/memory/cache.py` | A TTL cache for **model completions only**. A cached Prometheus read answers with the past, and during an incident that is exactly when it matters - so connector responses are deliberately not cached. A hit is recorded at **zero cost**, because replaying the original would make "what did this investigation spend" climb while no money moved. | 2 |
| `core/memory/vector_store.py` | ⏸ **Deferred to Phase 5**, with the trigger named in [ADR 0008](adr/0008-memory-layer-scope.md). Its only consumer is Mnemosyne, which declares no memory tool yet - and building a store with no reader means guessing the query shape two phases early. | 5 |
| `core/llm/assembly.py` | The default wiring for a `Delphi`, kept out of `gateway.py` so the injection point stays injectable. Refuses to build a gateway with no usable provider: an empty one fails deep in the fallback chain with "no adapter", which reads as a broken catalogue rather than a missing key. | 2 |
| `tests/unit/test_hermes_nl_query.py` | What Hermes runs, refuses and never claims, against a scripted model rather than a live one. Every case is about refusing to act on the part of a model's reply there is no reason to trust. | 2 |
| `agents/log_clustering/agent.py` | **Lethe.** Reports log patterns whose absence from the preceding window is *surprising*, plus exception traces. Each finding names the **narrowest resource every occurrence shares** - a pod, else the service, else the stream - because a pattern nobody can attribute cannot be correlated with a metric anomaly on the same pod. Detects **three of five** simulator scenarios and says which two it cannot: a fault that multiplies an existing pattern is invisible, because the rate test that would catch it could not tell a fault from the time of day and was deleted. | 2 |
| `tests/unit/test_lethe_detection.py` | What Lethe emits, refuses and never claims. The blind spot is pinned by a test, not only stated in prose - a limitation that lives only in a docstring gets fixed by accident and re-broken the same way. | 2 |
| `agents/log_clustering/templates.py` | **Lethe's method.** Log templates by *measuring* which fields vary across the corpus rather than masking what looks variable - a regex list encodes what its author had seen. A field is variable when it has too many values **or** when it is a sequence: cardinality cannot tell a clock from a status code, and a compressed run put `ts` inside every template. A group too small to tell says so instead of guessing. | 2 |
| `docs/lethe-predictions/` | Numbers written before the measurement that decides them. Eight rounds committed, including the six that were wrong - six of them were tuning a rule against one dataset, and what actually fixed it was a defect in the simulator. | 2 |
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
| `api/routers/webhooks.py` | Inbound webhooks. GitLab today; **no simulator-specific handling**, because real GitLab must hit the same path. | 1 |
| `core/bus.py` | The internal event bus. In-memory until Phase 2; the Protocol is the seam. | 1 |
| `core/contracts/plan.py` | `PlanStep` and `StepStatus` — the **execution record**. Its own module because `Investigation` needs `Verdict` and `Verdict` needs the plan; the cycle is the signal that the plan is a third thing. A finding list answers *what was claimed*; only this answers *what ran*. | 1 |
| `core/registry/loader.py` | Discovers and validates every `agents/*/manifest.yaml`. The only thing that knows where agents live. | 1 |
| `core/registry/capabilities.py` | Capability → agent matching, exact by name. Zeus plans by capability, never by agent. | 1 |
| `agents/_base/base_agent.py` | The shape ten agents repeat. A subclass provides one coroutine; the runtime owns the manifest, the tool allowlist, the budget, deterministic Finding ids, and **DEGRADED** — constructed in exactly one place. | 1 |
| `agents/_base/tool_binding.py` | The manifest as an **allowlist**, not documentation. Undeclared tools are refused at bind and at call; every call is counted against the budget. | 1 |
| `connectors/_base/python/base_server.py` | The Python MCP server shape, mirroring `pkg/mcpserver` field for field. `Tool.mutating` is a **field, not a naming convention** — the read/write split is what guardrails hang off at Phase 3, and inferring it from a verb would make a security boundary a spelling exercise. | 1 |
| `connectors/prometheus/` | Read-only MCP server: `query_range`, `query_instant`, `series` — exactly the three Argus declares, asserted in both directions. HTTP paths are an allowlist, so a future Prometheus release adding a destructive endpoint cannot silently become reachable. | 1 |
| `connectors/alertmanager/` | Alerts and silences, and the repository's **first write tool** - `create_silence`, `mutating=True`, reachable only through the executor. Bounded at both ends and capped at 24h, because a silence that outlives the incident is how an outage goes unnoticed for a weekend, and Alertmanager accepts an unbounded one. The *trigger* path is the receiver below — Alertmanager pushes; Pantheon does not poll, because Alertmanager owns grouping, inhibition and repeat intervals. | 1 |
| `deploy/observability/prometheus/rules.sim.yml` | ⚠️ **Simulator only.** One alerting rule per scenario. Every rule is a **gauge or a ratio**, because counters read `speed`× fast under compression and an absolute counter threshold would fire at one speed and be unreachable at another. Guarded against reaching any deployment path, like the config beside it. | 1 |
| `deploy/observability/alertmanager/alertmanager.sim.yml` | ⚠️ **Simulator only.** Seconds-scale grouping, one webhook receiver pointing at the real `/webhooks/alertmanager`. | 1 |
| `api/routers/alerts.py` | `POST /webhooks/alertmanager`. Same discipline as the GitLab hook: no simulator coupling, 202 not 200, and the payload stored **verbatim** — Alertmanager's schema varies by version, and the fields discarded today are the ones an investigation needs tomorrow. | 1 |
| `api/routers/agents.py` | The roster and one manifest whole. Each row carries `implemented`, read from the dispatcher's registry rather than the manifest - ten manifests validate and one agent runs. | 1 |
| `api/routers/approvals.py` | The way a person answers. Carries **no decision authority**: every check lives in the gate, and a second copy here is how the two drift. The Action is sent back in so the gate validates against the object the caller holds - the one about to be executed - rather than a stored copy that may already have diverged. Refusals are **409**, because the request is well-formed and it is the state that says no. | 3 |
| `api/routers/health.py` | Liveness, readiness and build-info. Readiness returns its per-dependency checks and **503s** when any fails, because a 200 with `ready: false` is read as ready. | 1 |
| `tests/unit/test_api_agents_and_health.py` | The roster, readiness and build-info, offline: a readiness probe opening a real socket would hang rather than fail on this platform. | 1 |
| `agents/_base/testing.py` | Fakes, including connectors that fail — the ones worth having. | 1 |
| `core/config.py` | **The only module that reads the environment.** pydantic-settings, one group per subsystem (`settings.prometheus.url`), env-var names unchanged from `.env.example`. Dev-shaped defaults for URLs; secrets have none and `PANTHEON_ENV=production` refuses to start without them. | 1 |
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
| `simulator/cluster.py` | The fake topology: 3 nodes, 12 pods, 5 services. Metrics and logs describe **these** entities, so the two streams correlate. Fixed rather than randomised, because a failed scenario has to reproduce. | 1 |
| `simulator/clock.py` | Compression as a parameter. `SimClock(speed)` maps simulated seconds to wall seconds; `speed=1` is real time. | 1 |
| `simulator/scenario.py` | Scenario model and YAML loader. Phases carry deviations (`factor` xor `offset`, one of four shapes) and log patterns; `expected_root_cause.category` is a `RootCauseCategory` from the contracts, not a free string. | 1 |
| `simulator/metrics_generator.py` | Baselines with **daily seasonality, a weekly cycle and gaussian noise** — never flat lines. Pushes a full snapshot per tick to the pushgateway. | 1 |
| `simulator/log_generator.py` | Structured logs to Loki for the same pods. Volume is **uniformly sampled** at high compression, never clipped per pod: a per-pod ceiling would erase the daily cycle and the busy/quiet gap. Ratio is reported on the run report. | 1 |
| `simulator/pipeline_generator.py` | GitLab Pipeline and Merge Request hook payloads, posted to the **real** webhook over real HTTP. No simulator-only route. | 1 |
| `simulator/runner.py` | The run loop. Reports `achieved_speed` and `kept_up` — pushing costs wall time, so beyond `tick_seconds / 0.29` a run silently falls behind, and silence is the failure worth preventing. | 1 |
| `simulator/cli.py` | `pantheon-sim run <scenario> [--speed N]`, `baseline`, `list`. | 1 |
| `simulator/scenarios/` | Five YAML scenarios driving the demo and e2e tests, one per root-cause category. | 1 |
| **codegen/** | The contract pipeline: `export_schemas.py`, `gen_go.sh`, `gen_ts.sh`, `verify.sh`. | 0 |
| **tests/** | Cross-cutting `unit/`, `integration/`, `e2e/`, `fixtures/`. Agent-local tests live in `agents/*/tests/`. | 1–5 |
| **deploy/** | Everything needed to run Pantheon somewhere. | 6–7 |
| `deploy/docker/` | Seven Dockerfiles, one per image. | 6 |
| `deploy/compose/` | Base, dev and observability stacks. **dev** carries Prometheus, Loki and the pushgateway the simulator writes into; **obs** is purely additive (Grafana, Tempo, OTel) so all three files stay independently valid under `docker compose config`. A fourth `sim` overlay would have defined `prometheus` and `loki` twice. | 6 |
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
| `docs/argus-predictions/` | What each Argus calibration measurement was expected to produce, written **before** it ran, with falsification conditions - and its **scoring** beside it. A prediction without its committed scoring is half a record. | 1 |
| `docs/argus-predictions/data/` | The raw measurements the scorings cite, committed because they otherwise live only in a session scratchpad. | 1 |
| `docs/argus-threshold-matrix.md` | How every number in `calibration.py` was derived: floors from one half of a ten-run set, thresholds from the other, and what the configuration cannot do. | 1 |
| `tests/unit/test_argus_detection.py` | What Argus emits, refuses and never claims - the properties that need no live stack. | 1 |
| `tests/integration/test_argus_detection_flow.py` | The live gate, both directions: a clean baseline three times over produces no anomalies, and each scenario is detected on the series that moved. | 1 |
| `core/orchestrator/` | Zeus: classify, plan, dispatch, aggregate. An alert plans **two** steps - metrics and logs both cover it - and a human question plans one, to Hermes. The verdict still proposes no hypotheses: **Delphi is no longer the blocker**, correlation is - the step that decides two findings describe one event. | 2 |
| `core/store/investigations.py` | Where an Investigation lives between the run that made it and the read that wants it. Postgres, one JSONB document, table created on first use. | 2 |
| `core/store/postgres.py` | The driver half, split off because it is **exempt from the coverage floor** - every line needs a live database and every line runs under `make test-flow-one`. | 2 |
| `connectors/loki/` | Read-only MCP server: `loki.query_range`, `loki.labels` - exactly the two Lethe declares, asserted in both directions. HTTP paths are an allowlist, so Loki's delete API (which removes log lines permanently) cannot become reachable by accident. | 2 |
| `tests/integration/test_loki_connector.py` | The live gate. Loki answers an empty result **differently per endpoint** - the label endpoints omit `data` entirely, `query_range` sends it with an empty `result` - and this is what measures which, so the offline tests encode Loki's behaviour rather than someone's memory of it. | 2 |
| `core/cerberus/store/master_key.py` | Resolves `CERBERUS_MASTER_KEY`, or **refuses**. No generated fallback: a key invented at startup makes every stored credential unreadable after the next restart, and the failure reads as corruption rather than as missing configuration. | 3 |
| `core/cerberus/store/envelope.py` | Envelope encryption. A fresh AES-256-GCM data key per credential, wrapped by the master key. Per-credential keys because a shared key means a shared nonce space, and GCM leaks its authentication key on nonce reuse - and because rotation then rewraps metadata instead of re-encrypting every secret. | 3 |
| `core/store/providers.py` | Configured LLM providers. `StoredProvider.has_key` is a **boolean**; `reveal_key` is the single, greppable door to a plaintext key. The in-memory store seals exactly as Postgres does, so a test cannot pass there and fail here. | 3 |
| `core/store/postgres_providers.py` | The driver half, **exempt from the coverage floor** - every line needs a live database and every line runs under `make test-providers`. `row_to_stored` stayed behind: it takes a mapping and opens no connection. | 3 |
| `api/routers/providers.py` | Provider CRUD, plus `GET /providers/{id}/models`, `PUT /providers/{id}/tiers` and **`POST /providers/{id}/probe`** - on demand only, because every probe is a paid request, and it defaults to what this deployment configured rather than everything the vendor lists. The key **never comes back**, not even masked. Model lists are asked of the provider rather than read from config, and a tier bound to a model the provider no longer serves is reported here - at settings time, where it costs nothing, rather than mid-investigation. | 3 |
| `tests/integration/test_provider_store.py` | The gate that earns the exemption above. Reads the `sealed_key` column on a **second connection** and asserts the plaintext is not in it - the one claim a unit test cannot make, since it reads back through the object that sealed it. | 3 |
| `tests/unit/test_coverage_exemptions.py` | An exemption must name a gate the Makefile defines, say what that gate covers, and point at a module that exists. | 2 |
| `tests/unit/test_orchestrator.py` | What Zeus plans, what it refuses to plan, and what its Verdict will not claim. | 2 |
| `tests/integration/test_flow_one.py` | The live gate for flow 1, both directions, reading the result back on a second connection. | 2 |
| `tests/unit/test_prediction_records.py` | Asserts every prediction record is **tracked by git**, not merely present on disk, carries a scoring, and cites measurements that exist. `55b0360` was one branch deletion from gone. | 1 |
| `tests/unit/test_simulator_tables_are_read.py` | For every metric and every per-metric table, asserts that perturbing the entry changes what the **exporter** emits. `require_every_metric` proves a table is complete; this proves it is read. | 1 |
| `docs/adr/` | Eight Architecture Decision Records, indexed in `docs/adr/README.md`. One (0007) is **Proposed**, not implemented. | 0 |
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
| A new **configurable value** | a typed field on the right group in `core/config.py`, **and** an entry in `.env.example` | Never `os.environ.get()` at the call site |
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


### Waiting is not work

[ADR 0007](adr/0007-deferred-actions.md) · **Proposed** · Phase 3 at the earliest

**An agent that starts an operation outlasting its budget completes its run
immediately and is resumed with the result.** `AgentBudget.max_seconds` is 120;
a CI bisect takes 5-40 minutes and a chaos experiment up to 90. Today such an
agent either blocks past its budget and dies, or fires and forgets and never
learns the outcome.

Wall-clock waiting must **not** count against `max_seconds` - only active work
does, or the same agent passes or fails depending on how busy an unrelated build
queue was that afternoon. A resumed agent gets the **remainder** of its original
budget rather than a fresh one: a retry repeats work, a resumption continues it,
and a fresh budget per deferral makes the total unbounded.

**Chronos** owns this, as infrastructure beside Delphi and Cerberus - consulted,
never dispatched to, no roster entry and no manifest. Completion is webhook
first, then polling where each poll is a tool call counting against budget, and
a **mandatory deadline** behind both. On expiry the agent produces a DEGRADED
Finding saying what it started and that the outcome was never learned: an
investigation that waits forever is worse than one that fails, because a failure
is read and a wait is assumed to be progress.

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
- When the feature is complete, push it and open a pull request:
  ```bash
  git push -u origin feature/<name>
  gh pr create --base develop
  ```
- **CI runs on the PR, and the merge waits for it.** A person merges on GitHub
  using the merge-commit option once the `CI` check is green - never a local
  `git merge` targeting `develop` or `main`. Branch protection on both branches
  enforces this.
- **Announce the branch name before starting it**, and confirm the merge and
  deletion when finishing it.

> This changed on 2026-08-19. Merging locally and pushing meant CI ran *after*
> integration, as a report - which is how sixteen red runs accumulated on
> `develop` unnoticed. A check consulted after the decision is documentation.
> See [CONTRIBUTING](../CONTRIBUTING.md#why-the-merge-moved-to-github).

---

## Commands

Every Makefile target. Targets are wired branch by branch during Phase 0; a
target that is not yet wired says so and exits non-zero.

| Target | Does | Live? |
|---|---|---|
| `make help` | List every target (default goal) | ✅ |
| `make install` | `uv sync` + `pre-commit install`. Go has no external deps; dashboard deps land on branch 4 | ✅ |
| `make dev` | Run the API locally with reload (`uvicorn --factory`, `/health` live) | ✅ |
| `make sim` | Run a simulator scenario against the local stack (`SCENARIO=`, `SPEED=`) | ✅ |
| `make test` | `pytest -m "not integration"` with coverage, then the per-module floor | ✅ |
| `make test-sim` | Run the simulator against a live stack and assert on the **data** it produces — variance, seasonality, separability, timing | ✅ |
| `make test-go` | `go build` + `go test` in every module listed in `go.work` | ✅ |
| `make test-ts` | Dashboard test suite (`vitest`) | ✅ |
| `make lint` | `ruff check` + `ruff format --check` | ✅ |
| `make lint-go` | `go vet` + `golangci-lint` in every module listed in `go.work` | ✅ |
| `make lint-ts` | `biome` + `tsc --noEmit` against the dashboard | ✅ |
| `make typecheck` | `mypy --strict` over the Python tree | ✅ |
| `make codegen` | Regenerate JSON Schema, Go structs and TS types | ✅ |
| `make codegen-verify` | Fail if generated output has drifted | ✅ |
| `make up` | Start the local Compose stack (`PROFILE=llm-local` for local models) | ✅ |
| `make down` | Stop the local Compose stack | ✅ |
| `make clean` | Remove build artifacts and tooling caches | ✅ |

A target that is not live names what it is waiting on and exits non-zero. None
of them silently succeed.

### Integration gates, and which of them CI can run

Each gate under `tests/integration/` declares the services it needs, via
`requires(...)` in `tests/integration/conftest.py`. A gate that needs the API
cannot run in a job that starts only Prometheus, and declaring it is what stops
one being swept into the other's target — which is exactly what happened when
`make test-sim` ran the whole directory.

| Gate | Needs | Target | CI |
|---|---|---|---|
| `test_simulator_data.py` | prometheus, loki, pushgateway | `make test-sim` | ✅ **runs in CI** — `ci-python.yml` starts those three |
| `test_connector_path.py` | prometheus, pushgateway, **api** | `make test-connectors` | ⬜ **local only** — no CI job starts the API yet |

`test_connector_path.py` does not run in CI today. That is stated rather than
left implied: it is a gate that exists and never executes, which is the same
false-green shape this repository keeps finding. ROADMAP carries the row for
wiring it.

Every row above was verified by **running the target**, under GNU Make 3.81
(GnuWin32) on Windows and under whatever CI provides on `ubuntu-latest`. That
distinction earned itself: the targets had previously only been exercised by
running their *bodies* by hand, and three defects were sitting in the Makefile
that only invocation could reveal — `test-sim` missing from `.PHONY`, a
two-line `##` comment that put a nameless row in `make help`, and a default
`SPEED` above anything the runner could deliver. `tests/unit/test_makefile.py`
now parses for those shapes on every commit.

`SHELL := /usr/bin/env bash` means a POSIX shell is required. On Windows that is
satisfied by Git for Windows' bash, which GnuWin32 make invokes without trouble;
no 3.81-specific workaround is in the file.

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
| 2 | Orchestrator & Investigation Flow | **Zeus** end to end, completion cache ([ADR 0008](adr/0008-memory-layer-scope.md) — the vector store is deferred), LLM provider, **Lethe** + **Hermes**, Loki connector |
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
| 2026-08-18 | `feature/sim-alert-rules` | **Flow 1 can run: a scenario now fires an alert.** Until this branch the simulator wrote metrics and nothing turned them into one, so the trigger half of *"an alert produces a Finding"* had never executed. Five rules, one per scenario, wired through a sim-scoped Alertmanager to the receiver. **Every rule is a gauge or a ratio of two rates** — the compression factor cancels in a ratio and never touches a gauge, so a rule means the same thing at 1× and 500×; a guard fails the build on a bare `rate()` compared to a constant. Windows and holds are checked against `range + for < fault_simulated_duration / speed`, which **caught a rule that could never fire** (a 90s window against a 60s visible fault) before anything ran. `flaky_test_storm` keeps its defining property — production metrics stay flat — by alerting on a new `pantheon_ci_pipeline_failure_ratio` gauge, which is CI telemetry rather than a production symptom. Thresholds are measured from the generator, not chosen by feel. Seven unit guards planted; empirical gate runs **both directions per rule**, because only the clean-baseline case distinguishes a detector from an alarm that fires on everything. |
| 2026-08-21 | `feature/argus` | **Peer-relative comparison, and two refusals.** `agents/anomaly/calibration.peer_z` compares a series against its peers at one instant instead of against its own past: seasonality is common-mode across peers, so it cancels with **no window and no period estimate** - which is the temporal path's production blocker. Two hard preconditions, neither a filter to relax. **Group size**, because below twelve the estimator degenerates: a seeded sweep over live baseline found 100% of three-peer subsets exceed |z| = 8, worst case 9444, and `disk_ratio` at three nodes duly produced 1599.63 on a *clean* baseline in one scenario and 1585.74 as a *signal* in another - the same degeneracy wearing opposite labels. **Complete coverage**, because comparing whichever peers reported is silently a different, smaller group. `MIN_PEERS = 12` is provisional - the only size measured as a whole population rather than sampled. Peer-relative has a replica-count limitation to set against the temporal path's period estimation, recorded in ROADMAP. |
| 2026-08-20 | `feature/argus` | **Argus, statistical only — contract, then calibration.** Added `agents/anomaly/calibration.py`: the detection parameters, the records they were derived from, and the rule that an aggregate cannot be computed from run records without their degradation status. `WINDOW_SECONDS = 90` was chosen for the **lowest baseline excursion**, not the largest peak — peak z would have picked the worst window, since `memory_leak` peaks at 43.9 with a 20s window and covers 2% of its fault against 12.8 and 48% at 90s. `MEASURED_COVERAGE` declares that `disk_pressure` is **onset-only**: a trailing-window estimator goes blind to a fault that outlasts its window, measured at peak z 700 against tail z 1.4, and no window length hides it. `ScenarioRunner` now survives a log-sink failure and records `degraded`, because Argus reads metrics and a Loki outage must not abort a metric measurement — but a run that proceeds silently without logs differs from the conditions being characterised, so the tolerance is visible in the report. **Contract first.** `MetricWindowPayload` lost `baseline_mean`/`baseline_stddev` and gained `baseline_centre`, `baseline_scale` and a `BaselineEstimator` enum. `MetricWindowPayload` loses `baseline_mean`/`baseline_stddev` and gains `baseline_centre`, `baseline_scale` and a `BaselineEstimator` enum. Detection is **median / 1.4826 x MAD**, and writing a median into a field named `baseline_mean` is a number that looks meaningful and is not - a reader would compare it against a mean from elsewhere, which differs most exactly under the contamination that matters. The old fields were **removed rather than kept alongside**: two estimators side by side invite that comparison, and the displayed one would be the one that breaks. The estimator is an enum rather than free text, so it survives codegen as a closed set in Go (validated on unmarshal) and TypeScript (a union) - a `str` field is where `median_mad`, `MAD` and `robust` all appear within a month. `NOT_APPLICABLE` is a member rather than `None` because `test_schema_contains_no_nullable_enum` forbids nullable enums, which emit a duplicate `UnmarshalJSON` in Go; that guard caught this design on its first run and the explicit member is the better shape anyway. Guarded both ways: a centre or scale without an estimator is rejected, and the closed set is asserted **in the generated artifacts**, not only in Python - a closed set is worth nothing if it reaches the dashboard as a bare string. |
| 2026-08-19 | `fix/simulator-phase-window` | **Three of the four deviation shapes did nothing.** `phases_at` decided a phase was running from `simulated_seconds - baseline_seconds`, while `MetricsGenerator.sample` computed how far through it was from **absolute** time against a baseline-relative `start_seconds` - so progress never fell inside [0, 1]. Measured through `memory_leak`'s leak it ran **2.18 to 3.18**, clamped to 1.0 for every sample of every run. At that progress `ramp` is indistinguishable from `step`, and `spike` and `sawtooth` are **0.0** - inert. `memory_leak`'s OOM sawtooth and `disk_pressure`'s eviction spike had never changed a number. Replaced `Scenario.phases_at` with `Scenario.active_at`, returning an `ActivePhase` that carries the phase **and** its progress, so activity and progress cannot be measured from different origins; the same computation had been written in three places against two origins, including a second copy in `_node_disk`. The guard that should have caught it exhibited two named failure modes at once - aimed at `_apply` rather than at `sample`, and planted only with the default shape, which is the one shape that passes at progress 0.0 - and consequently read as verified from both directions. Now four guards, each planted: absence before the phase for **every** shape, every shape moving the metric somewhere inside its phase, progress staying in [0, 1) across a **real** scenario, and `_node_disk` climbing as a ramp rather than as drift. Alert-rule thresholds are **not** re-measured here: the rules live on `feature/sim-alert-rules`, and every one of them was measured against this generator. |
| 2026-08-19 | `fix/ci-green` | **Fifteen red CI runs, five causes, none reproducible locally.** Go: every `go.mod`, `go.work`, the connector Dockerfile and both workflows move to **1.25** (the pinned generators need it), with `GOTOOLCHAIN: local` declared so a toolchain switch is an error rather than a line printed on every local run - which is how the mismatch stayed invisible for days. `make test-sim` swept the whole integration directory, so gates needing services CI does not start were dragged in; `tests/integration/conftest.py` now has each gate declare its stack with `requires(...)`, skipping normally and failing under `PANTHEON_REQUIRE_STACK`, and each gate gets its own Makefile target. **pnpm's `packageManager` was never read**: `action-setup` looks at the repository root, there is no root `package.json`, and three files claimed otherwise - `git log -S` shows the asserting guard never existed. Overrides moved to `dashboard/pnpm-workspace.yaml`, since pnpm 10+ ignores the `pnpm` key in `package.json`. `connectors/kubernetes/Dockerfile` held only comments, which **aborted** trivy rather than failing it - deleting it let the scan finish and surface five HIGH misconfigurations it had been hiding, fixed by giving MinIO and the backup CronJob the hardened `securityContext` every other workload already had. **`trivy config` then failed reporting "CRITICAL or HIGH" on 37 findings that were 28 LOW and 9 MEDIUM:** `severity` does not filter SARIF, so `exit-code: 1` in the same step gated on everything while the declared threshold gated on nothing, and `trivy fs` had the same defect and passed for want of findings. Report and gate are now separate steps, the gate printing `table` so a failure states its reason in a log SARIF leaves empty. Added `tests/unit/test_ci_is_runnable.py` (15 guards) and `.trivyignore` (KSV-0109 fires on `LLM_MAX_TOKENS`, a token *count*; the inline `# trivy:ignore:` had done nothing because rendering strips template comments). An audit of every "X is guarded" claim across the map, README, CONTRIBUTING, the ADRs and the workflow comments found two more with no mechanism: CONTRIBUTING's "a guard checks each" of three steps for adding a setting, where the third had none and four `SecretStr` fields had drifted outside `REQUIRED_IN_PRODUCTION`; and the README's counts, stale at 19 models and 78 guards against 49 and 279. Both now guarded. |
| 2026-08-18 | `feature/prometheus-connector` | **The first real connectors, read-only and proven so.** `connectors/_base/python/` implements the MCP server shape mirroring the Go side, with `Tool.mutating` as a declared field rather than a naming convention. Prometheus exposes exactly the three tools Argus declares — asserted in both directions, so the allowlist has real subjects instead of being enforced against nothing — and Alertmanager adds two. HTTP paths are an allowlist rather than a denylist. `api/routers/alerts.py` receives real Alertmanager notifications, stores the payload verbatim and publishes `TriggerReceivedEvent`. Added `mcp` 1.29 and `make test-connectors`. Six unit guards and an empirical gate, all planted: a real PromQL query returning simulator data, a malformed query reported rather than swallowed, and the allowlist distinguishing `ToolNotDeclared` from `ToolNotBound` with a passing control between them. |
| 2026-08-18 | `feature/agent-runtime` | **The agent runtime, and the shape ten agents will repeat.** `core/registry/` loads and validates all ten manifests and matches capabilities exactly; `agents/_base/` gives a subclass one required coroutine and owns everything else. The manifest is an **allowlist** — Argus cannot reach Loki — enforced at bind and at call, with every call counted. `FindingKind.DEGRADED` is constructed in exactly one place and a guard fails the build if an agent builds its own. Finding ids are **deterministic** (uuid5 over investigation, agent, kind, subject, window and title, deliberately excluding `detected_at`), so a Temporal retry cannot duplicate a claim — mechanism rather than a docstring asking subclasses to be idempotent. `Verdict.steps` is now **required** and `partial` is derived from it, so a verdict cannot be formed without knowing what ran and cannot claim completeness while agents degraded; this extracted `core/contracts/plan.py` to break the resulting import cycle. Guards: 14 planted both ways, plus one asserting nothing reads `max_tokens` yet. **Two real defects found by the guards:** `run()` promised never to raise but stamping ran outside the guard, so a malformed Finding escaped; and the allowlist guard passed for the wrong reason, because an undeclared tool and an unbound tool raised the same exception — now `ToolNotDeclared` and `ToolNotBound`. |
| 2026-08-18 | `feature/centralized-config` | **One module reads the environment; everything else imports from it.** Added `core/config.py` (pydantic-settings, nested groups per subsystem, 51 variables) and migrated every call site — `api/routers/webhooks.py`, the four simulator modules, the CLI and the integration gate. Four guards, each planted both ways: nothing outside `core/config.py` touches `os.environ`; no hardcoded endpoint outside it; `.env.example` and the model agree in **both** directions; and a missing secret fails at startup under `PANTHEON_ENV=production`. A fifth guards that Go reads only variable names the template declares — it has no live subjects yet, since the Go modules read nothing, and was verified by planting one. **Two real defects found by running it:** the API container never received the connector endpoints, so in-container config fell back to `localhost` rather than the Compose service names; and no Python image installed the project, so `importlib.metadata` found no distribution and `/health` served the `0.0.0+not-installed` placeholder from a container that was otherwise healthy. Both fixed and guarded. Added `.gitleaks.toml`: `.env.example` is excluded because the generic-api-key rule fires on `CERBERUS_MASTER_KEY=` on the variable name alone — a **transfer** of responsibility, not a removal, since a guard now requires every `SecretStr` field to be empty in the template, driven by the model rather than by name-shape guessing (which flagged `LLM_MAX_TOKENS` and `S3_ACCESS_KEY`). Secret scanning elsewhere is unchanged, verified by staging a real GitLab PAT. Also made the gate's readiness budget asymmetric: 12s when a missing stack means skip, 60s when `PANTHEON_REQUIRE_STACK` asserts it must be there — `make sim` pushing 268k lines leaves Loki busy for longer than twelve seconds, and busy is not absent. |
| 2026-08-17 | `refactor/mechanism-helper` | **Comment-stripping made the default instead of a convention.** `_mechanism_only()` moved out of `test_repo_structure.py` into `tests/mechanism.py`, and all 63 file reads across fourteen test modules were classified individually: `read_mechanism` (22, scanned), `read_data` (25, parsed), `read_verbatim` (14, the comments *are* the assertion, reason required), `read_scannable` (2, repo-wide sweeps). `tests/unit/test_mechanism_helper_is_used.py` now fails the build on any raw read — the doc-satisfies-mechanism bug had been fixed five times and kept returning because the fix lived in one file while `Path.read_text()` stayed the obvious thing to type. `read_mechanism` refuses Markdown, because stripping `#` would have turned the map's heading guard into one that asserts nothing. Also turned `test_contracts.py`'s leftover `pytest.skip` into an assertion — the skip audit's one real finding: a scenario with no `expected_root_cause` was reported as a pass. ROADMAP phase headings now carry status, so Phase 1 cannot read as finished while four of its six items are stubs. |
| 2026-08-17 | `fix/version-single-source` | **One version, declared once.** `/health` served `0.1.0` throughout the v0.2.0 release: the number was written down in five places and only the tag moved. `api/__init__.py` now reads it from installed package metadata (`importlib.metadata`), so `pyproject.toml` is the single declaration and nothing Python can drift from it. The three manifests that cannot read Python metadata — Helm `version` and `appVersion`, `dashboard/package.json` — are held equal by `tests/unit/test_version.py` instead of by memory, and all three were stale. Added a guard that a `v*` tag pointing at HEAD must match the declared version, verified by planting both a mismatched and a matching tag; `ci-python.yml` now fetches tags, without which it would have passed vacuously in CI. **One guard was removed for being unfailable:** pyproject-versus-installed-metadata cannot disagree because `uv run` re-syncs before every invocation, so planting a mismatch just reinstalls. The release step is documented in CONTRIBUTING. |
| 2026-08-17 | `fix/makefile-verification` | **The Makefile had never been run.** GNU Make was not installed, so every target had only been exercised by running its body by hand — which cannot see the Makefile itself. Installing Make 3.81 and running all seventeen targets found three defects: `test-sim` was missing from `.PHONY`; a two-line `##` comment put a nameless row in `make help`; and `sim` defaulted to 4320x, above anything the runner can deliver at a 60s tick, so the honest "fell behind" warning fired on every ordinary run and was on its way to becoming noise. **Worse, `make test-sim` skipped all nine tests and exited 0** when Loki was briefly unready after `make sim` pushed 240k lines into it — a gate reporting success having asserted nothing, which is the exact failure the CI job's readiness check was written to prevent, reproduced locally where no such check existed. The target now sets `PANTHEON_REQUIRE_STACK` and the fixture fails instead of skipping; a bare `pytest` on a laptop still skips. Readiness is retried as one bounded loop rather than decided by a single probe. Added `tests/unit/test_makefile.py` (7 guards, all planted) and `simulator.runner.max_honest_speed`, which the default `SPEED` is held under so the two cannot drift. No 3.81-specific workaround was needed. |
| 2026-08-17 | `feature/simulator` | **The simulator, gated on its data rather than its shape.** Added `cluster.py` (3 nodes, 12 pods, 5 services — metrics and logs describe the same entities), `clock.py`, `scenario.py`, `metrics_generator.py`, `log_generator.py`, `pipeline_generator.py`, `runner.py`, `cli.py`, five scenarios covering five distinct `RootCauseCategory` values, `make sim` and `make test-sim`. Baselines carry a skewed diurnal cycle, a weekly cycle, per-pod phase jitter and per-metric gaussian noise. **Three defects were found only because the gate asserts on data:** `RESTARTS` was absent from all three metric tables, so the generator raised `KeyError` on its first push; log volume was clipped per pod, which at any real compression makes the busiest service at 14:00 emit exactly what the quietest emits at 04:00 — the flat line the metrics avoid, moved into the log domain, fixed with a uniform sampling ratio that is reported on the run report; and the run loop slept a fixed duration per tick, so OS timer overshoot (~16ms, and `sleep` can only overshoot) accumulated 554 times and silently turned a requested 2880x into 1880x. `RunReport` now carries `achieved_speed`/`kept_up`, pacing is against an absolute schedule, and the pushgateway push reuses a connection (290ms → 102ms per tick). 33 unit guards, 15 planted in both directions — **one of which failed its own planting** and was rewritten a level up, recorded in `docs/guard-verification.md`. Added a `simulator` CI job that brings the stack up and asserts readiness, because a gate that skips when the stack is missing would otherwise report a pass. |
| 2026-08-17 | `feature/sim-observability-stack` | **The stack the simulator writes into, plus a guard for the project's own rule.** Added `prometheus`, `loki`, `pushgateway` to the **dev** overlay and made **obs** additive, so all three Compose files stay independently valid rather than two of them defining the same services. Added `deploy/observability/prometheus/prometheus.sim.yml` (1s scrape, `honor_labels`) kept separate from the production config, with a guard that fails if it is referenced from `deploy/helm`, `kustomize`, `argocd` or `terraform`. Added `core/bus.py` and `api/routers/webhooks.py` (GitLab Pipeline and Merge Request hooks → `TriggerReceivedEvent`), with a guard asserting the endpoint contains no simulator-specific code. Added `tests/unit/test_no_tautological_assertions.py` — the `or True` slip means the central rule now has mechanical enforcement rather than vigilance. **Empirical gate found a real break `docker compose config` could not: Loki exited on a root-owned volume; fixed with a `loki-init` one-shot.** |
| 2026-08-16 | `feature/contracts-expansion` | **Phase 1 domain model.** `Evidence.payload` became a discriminated union over five per-kind models (`EvidenceKind` and the union are guarded to stay the same set). Promoted `RootCauseHypothesis` with a closed `RootCauseCategory` vocabulary, replacing `Verdict.root_cause: str` — prose cannot be scored against ground truth. Added `ResourceRef`, `PlanStep`, `ActionReceipt`, `FindingKind.DEGRADED`, and validators on Finding/Action/Verdict/Investigation. Added the event members the ADRs already promised but the bus could not emit: `LeaseExpiredEvent` (ADR 0005) and `BreakGlassEvent` (ADR 0006), plus step/completion events. Filled the **ten agent manifests** and added a guard validating each against `AgentManifest` rather than merely asserting the file exists. Added `tests/unit/test_contracts.py` (20 guards) and `tests/unit/test_export_schemas.py` (34) — the exporter had sat at 0%. Coverage floor 0 → **95 aggregate**, plus a **per-module floor of 90** in `tests/coverage_floor.py` over modules that actually branch, because 61% of statements are declarations covered by import alone. |
| 2026-08-15 | `fix/enforce-lf-line-endings` | **Line endings enforced by the repository, not by each clone.** Added `.gitattributes`: `* text=auto eol=lf`, explicit LF for shell/source/config, CRLF for `.bat`/`.cmd`/`.ps1` (forcing LF there is the mirror-image bug), binary rules, and `linguist-generated` on the four generated artifacts and two lockfiles. Content was already clean — `core.autocrlf=input` had been normalising it — but that is a per-machine coincidence, and a clone with Windows' default `true` would have committed CRLF. Added a guard checking the **index** rather than the working tree, verified against three planted violations: a CRLF blob written straight into the index with `hash-object --no-filters`, the catch-all rule removed, and `.gitattributes` deleted. |
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
