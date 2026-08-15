# ADR 0004 — Delphi: the LLM gateway and provider abstraction

- **Status:** Accepted
- **Date:** 2026-08-15
- **Decided on branch:** `feature/neutrality-guard-narrowing` (design);
  structure lands on `feature/deploy-skeleton`
- **Implementation:** Phase 2. Settings surface: Phase 4.

## Context

Pantheon must work with **any** LLM provider, with model selection driven from
application settings. This is a headline capability, not a configuration
detail — it is the same commitment ADR 0001 makes for object storage, applied to
the component the whole platform depends on.

Three forces make the naive approach fail:

1. **The model landscape churns faster than the code.** Any list of models
   compiled today is wrong within weeks and, worse, silently excludes every
   model released after it was written.
2. **Eleven agents must not each know a model name.** If `agents/nl_query/`
   hardcodes a model, then switching providers is an eleven-file change plus a
   test sweep — and nobody will do it.
3. **Self-hosted must be first-class.** The stack has to run with **zero API
   keys**, or the local-first promise is hollow.

## Decision

**Delphi is the LLM gateway.** Agents consult the Oracle; they never choose a
model.

Delphi is **not an agent**. It sits beside the orchestrator as infrastructure:
no entry in the eleven-agent roster, no `manifest.yaml`, no capability
declaration. Zeus dispatches to agents; agents consult Delphi.

### The central invariant

> **Agents never name a model.** They declare `ModelRequirements`; Delphi
> resolves those to a concrete model at call time.

```python
# FORBIDDEN in any agent
response = provider.complete(model="some-vendor/some-model-v3", ...)

# The only sanctioned shape
response = delphi.consult(
    ModelRequirements(
        capabilities={Capability.TOOL_USE, Capability.JSON_MODE},
        min_context=32_000,
        tier=Tier.BALANCED,
        max_cost_per_call=0.02,
    ),
    prompt=...,
)
```

**Swapping providers in settings must require zero code changes across all
eleven agents.** That is the acceptance test for this design.

## Contract surface

Six types in `core/contracts/llm.py`, so they flow through the codegen pipeline
([ADR 0002](0002-codegen-from-json-schema.md)) to Go and TypeScript unchanged:

| Type | Role |
|---|---|
| `Capability` | enum — `TOOL_USE`, `JSON_MODE`, `VISION`, `STREAMING` |
| `Tier` | enum — `CHEAP`, `BALANCED`, `FRONTIER` |
| `ModelRequirements` | what an agent needs: capabilities, `min_context`, `tier`, `max_cost_per_call` |
| `ProviderConfig` | a configured provider: dialect, base URL, auth mode, model source |
| `ModelDescriptor` | one model as *observed*: id, context, probed capabilities, measured cost and latency |
| `ResolutionRecord` | why a given model was chosen for a given call |

`ResolutionRecord` is referenced from `investigation.py`, so resolution history
travels with the Investigation it belongs to.

## Resolution cascade

Delphi resolves `ModelRequirements` to a `ModelDescriptor` by taking the first
binding that satisfies them:

| # | Source | Why it sits here |
|---|---|---|
| 1 | **Per-task override** | The narrowest, most deliberate signal — an operator pinning one run |
| 2 | **Per-agent binding** | Standing policy: "Hermes always uses the frontier tier" |
| 3 | **Tier default** | The normal path; the tier comes from the agent's requirements |
| 4 | **Global default** | Last resort, so a fresh install works before anything is configured |

A binding that does **not** satisfy the declared requirements is skipped, not
used. An explicit override that cannot satisfy them is an error, not a silent
downgrade — otherwise an override becomes a way to quietly break an agent.

### Failure path

**fallback chain → budget guard → hard stop.**

1. **Fallback chain** — the next candidate that satisfies the requirements, in
   configured order. Covers provider outages and rate limits.
2. **Budget guard** — if the only remaining candidates exceed
   `max_cost_per_call`, or the Investigation's own budget, stop. Per-call cost
   enforcement **delegates to `core/guardrails/budget.py`** rather than
   duplicating policy; Delphi supplies the price, guardrails make the decision.
3. **Hard stop** — the Investigation fails loudly with the reason.

**Hard stop beats silent downgrade.** An agent that declared `TOOL_USE` and
silently received a model without it does not fail — it produces confident
nonsense, which is far more expensive to debug than an error.

## Auditability

Every resolution writes a `ResolutionRecord` onto the Investigation:
requirements, cascade step that matched, candidates rejected and why, the model
chosen, measured cost and latency.

A run is therefore reproducible and explains itself. "Why did this cost £4?" and
"why did Argus miss that?" are both answerable from the record, without
re-running anything.

Secrets never appear in a `ResolutionRecord` — see below.

## Provider adapters

Adapters are named by **wire format, not vendor**. A dialect outlives the vendor
that popularised it, several vendors speak each one, and vendor-named modules
imply a coupling that does not exist.

| Module | Dialect | Speakers |
|---|---|---|
| `chat_completions.py` ★ | `CHAT_COMPLETIONS` | OpenRouter, Groq, Together, DeepSeek, Mistral, vLLM, LM Studio, Ollama, OpenAI, and most self-hosted stacks |
| `messages.py` | `MESSAGES` | Anthropic and API-compatible gateways |
| `generate_content.py` | `GENERATE_CONTENT` | Google Gemini |
| `raw.py` | `RAW` | Bespoke HTTP APIs, mapped by configuration |
| `custom.py` | any of the above | User-defined providers from the settings UI |

**`chat_completions.py` is the reference implementation** and the highest-leverage
adapter by a wide margin: the majority of hosted gateways and effectively every
self-hosted stack speak that dialect. Get it right and "any provider" is already
mostly true. It is written first and the other adapters follow its shape.

### Custom providers — what makes "any provider" real

`custom.py` lets an operator add a provider **from the settings UI with no
code**:

- `base_url`
- `dialect` — one of the four above
- auth mode — bearer token, header key, query parameter, or none
- model source — a models endpoint to enumerate, or a manually entered list

Without this, "any provider" means "any provider we shipped an adapter for",
which is a different and much smaller claim.

## Capability discovery by probing

**There is no hardcoded model table.** Models describe themselves.

On **Test connection**, Delphi fires four probes at each model and records what
actually happened:

| Probe | Establishes |
|---|---|
| Trivial completion | reachability, auth, latency floor |
| Tool call | `TOOL_USE` |
| JSON-schema response | `JSON_MODE` |
| Tiny image | `VISION` |

Latency and cost are measured, not declared, and written to the capability
matrix.

The rationale is the same one that rules out a static model list: **a table
would be stale within weeks and would exclude every model released after this
code was written.** It would also be wrong in a subtler way — a model's
advertised capabilities and its behaviour behind a particular gateway are not
always the same thing. Probing measures the deployment, not the marketing.

Probe results carry a timestamp and are re-run on demand and on configuration
change.

## Secrets

`keyring.py` owns API keys:

- **encrypted at rest**, never stored in plaintext config;
- **never written to logs**, never attached to a `ResolutionRecord`, redacted in
  traces by `tracing.py`;
- supplied per environment: Compose reads from env vars, Helm from
  `existingSecret`, in-cluster from Sealed Secrets
  (`deploy/security/sealed-secrets/`).

A key that reaches an Investigation record is a security bug, not a cosmetic
one: Investigations are persisted, exported in reports and rendered in the
dashboard.

## Settings surface — Phase 4

The dashboard exposes:

- **Provider cards** — each configured provider with live status, its probed
  models, and a **Test connection** button that re-runs the four probes.
- **Tier default pickers** — which model backs `CHEAP`, `BALANCED`, `FRONTIER`.
- **Per-agent override table** — the cascade's step 2, editable.
- **Validation warnings** — computed from the capability matrix against each
  agent's declared requirements:

  > ⚠️ **Hermes** requires `TOOL_USE` — the **Cheap** tier model failed that probe.

**Misconfiguration must surface at settings time, not mid-investigation.** An
incident is the worst possible moment to discover that the bound model cannot
call tools. The matrix already holds everything needed to compute this, so the
warning is cheap; the alternative is a failed run at 03:00.

## Structure

```
core/llm/                         Delphi - the LLM gateway (Phase 2)
├── __init__.py                   public surface: consult(), resolve()
├── gateway.py                    ★ Delphi entrypoint; the only thing agents call
├── resolver.py                   the four-step resolution cascade
├── fallback.py                   fallback chain, budget guard, hard stop
├── capability_matrix.py          probe results: what each model actually does
├── probe.py                      ★ the four probes; backs "Test connection"
├── keyring.py                    ★ encrypted key storage, redaction
├── catalog.py                    configured providers; loads/validates ProviderConfig
├── provider.py                   adapter protocol every dialect implements
├── tracing.py                    prompt/response tracing, cost accounting, redaction
├── providers/
│   ├── __init__.py
│   ├── chat_completions.py       ★ reference adapter - highest leverage
│   ├── messages.py
│   ├── generate_content.py
│   ├── raw.py
│   └── custom.py                 ★ user-defined provider from settings, no code
└── prompts/                      shared system prompts
```

`catalog.py` is deliberately **not** named `registry.py`: `core/registry/` is
already the agent registry, and two registry modules in one package tree invites
import confusion and mis-greps.

## Deploy impact

Landing on `feature/deploy-skeleton`:

- **Helm** — a `delphi:` block in `values.yaml`: configured providers, tier
  defaults, and `existingSecret` for keys, mirroring the `minio:` block's
  external-passthrough shape.
- **Compose** — **Ollama as an optional service**, so `make up` gives a working
  stack with **zero API keys**. This is the local-first promise made concrete:
  a contributor with no accounts can still run an investigation end to end.
- **`.env.example`** — `LLM_*` and provider variables.

## Consequences

**Good**

- Provider swap is a settings change, not a code change — across all eleven agents.
- New models work the day they ship, because nothing enumerates models.
- Capability mismatches surface at configuration time.
- Cost and latency are measured per deployment rather than assumed.
- The stack runs with no cloud accounts at all.

**Costs**

- Probing costs a few tokens per model on connect, and must be re-run when a
  provider changes models behind a stable id.
- The capability matrix is a cache, and caches go stale; it needs a refresh
  policy and a visible "last probed" timestamp.
- One more indirection between an agent and its model, which makes a naive
  stack trace longer.
- Four dialect adapters to maintain, though `custom.py` absorbs most of the long
  tail.

## Alternatives considered

| Option | Why not |
|---|---|
| **Hardcoded model registry** | Stale in weeks; excludes new models; encodes marketing claims rather than observed behaviour. |
| **Per-agent model configuration** | Provider swap becomes an eleven-file change; capability mismatches stay invisible until runtime. |
| **A third-party multi-provider SDK** | Adds a dependency that gates which providers are reachable, and its abstraction is model-first rather than requirements-first — the wrong shape for the invariant above. Custom providers from settings would still not be possible. |
| **Environment variables only, no settings UI** | Cannot express per-agent overrides or surface validation warnings, and requires a redeploy to change a model. |

## Phase plan

| Phase | Delivers |
|---|---|
| **0** | Structure and contracts as documented stubs; `delphi:` Helm block; Ollama Compose service; env vars |
| **2** | `gateway`, `resolver`, `catalog`, `chat_completions`, `keyring`, `tracing`, `ResolutionRecord` persistence |
| **3** | Budget guard integration with `core/guardrails/` |
| **4** | Settings surface, probes wired to **Test connection**, validation warnings |
| **5** | Remaining dialect adapters and `custom.py` hardening |
