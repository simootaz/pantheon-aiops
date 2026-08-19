# Pantheon

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Phase](https://img.shields.io/badge/phase-0%20·%20scaffold-orange.svg)](ROADMAP.md)
[![Python](https://img.shields.io/badge/python-3.12-3776ab.svg)](pyproject.toml)
[![Go](https://img.shields.io/badge/go-1.23-00add8.svg)](go.work)
[![Next.js](https://img.shields.io/badge/next.js-15-black.svg)](dashboard/package.json)

A polyglot, multi-agent AIOps platform. Eleven specialists under one
orchestrator, investigating incidents, delivery health and capacity — with every
write action gated, every credential brokered, and every run auditable.

---

## ⚠️ Status: Phase 0 — this is a scaffold, not a working product

**No investigation has ever run.** Agents, orchestration and connectors are
documented stubs carrying `# TODO: Phase N` markers. If you clone this expecting
software that triages an incident, you will be disappointed within a minute, so
here is the honest split:

| What genuinely exists and works | What does not exist yet |
|---|---|
| **Contracts** — 49 Pydantic v2 models, the single source of truth | Agent implementations (all eleven) |
| **Codegen** — Pydantic → JSON Schema → Go + TypeScript, with drift detection | The orchestrator (Zeus) |
| **281 tests** — structural, security and type-level guards among them, each guard verified against a planted violation | Connectors (all seven) |
| **Deploy skeleton** — Helm lints and templates, Terraform validates, Compose runs | Delphi and Cerberus behaviour (structure and contracts only) |
| **CI** — 9 workflows, SHA-pinned, one required check | The AG-UI endpoint and A2UI surfaces |
| **Dashboard** — builds, with the AG-UI client and A2UI renderer | Anything that produces a Finding |
| **Six ADRs** recording the decisions and what was rejected | |

The interesting part right now is the **guards**, not the features. The
scaffolding enforces its own rules: the allowlist cannot drift from the
contract, agents cannot import the modules that hold plaintext, generated code
cannot be hand-edited, and the repository map cannot gain or lose a top-level
entry without a test failing. See
[docs/guard-verification.md](docs/guard-verification.md) — including the guards
that turned out not to work, and how each was discovered.

[ROADMAP.md](ROADMAP.md) has the phase plan.

---

## The eleven agents

| Codename | Domain | Role | Phase |
|---|---|---|---|
| **Zeus** | `core/orchestrator/` | Routes, classifies, plans, dispatches, aggregates | 2 |
| **Argus** | `agents/anomaly/` | Detects metric anomalies, correlates them into findings | 1 |
| **Lethe** | `agents/log_clustering/` | Clusters high-volume logs, surfaces novelty | 2 |
| **Hermes** | `agents/nl_query/` | Turns natural language into connector queries, and back | 2 |
| **Hephaestus** | `agents/ci_triage/` | Triages failing CI, separates flake from real regression | 4 |
| **Aegis** | `agents/manifest_review/` | Reviews manifests and IaC diffs for risk before rollout | 3 |
| **Moira** | `agents/capacity/` | Forecasts capacity, predicts saturation | 5 |
| **Mnemosyne** | `agents/knowledge/` | Recalls prior incidents, runbooks, tribal knowledge | 5 |
| **Clio** | `agents/reporting/` | Writes timelines, postmortems, executive summaries | 5 |
| **Themis** | `agents/dora/` | Computes DORA metrics, judges delivery health | 4 |
| **Eris** | `agents/chaos/` | Designs and supervises chaos experiments | 5 |

**Delphi** and **Cerberus** are deliberately *not* on that list. They are
infrastructure agents consult, not specialists Zeus dispatches to — no roster
entry, no manifest.

## Architecture

```mermaid
flowchart TB
    subgraph human["👤 Human"]
        OPS["Operator"]
    end

    subgraph ui["Interface — AG-UI transport · A2UI payload"]
        DASH["Dashboard<br/><i>Next.js 15</i>"]
        AGUI["AG-UI event stream<br/><i>SSE · StateSnapshot + StateDelta</i>"]
    end

    subgraph brain["Orchestration"]
        ZEUS["⚡ Zeus<br/><i>route · classify · plan<br/>dispatch · aggregate</i>"]
        GUARD["🛡️ Guardrails<br/><i>policy · approval · budget</i>"]
    end

    subgraph infra["Infrastructure — consulted, never dispatched"]
        DELPHI["🔮 Delphi<br/><i>LLM gateway</i><br/>requirements → model"]
        CERB["🐕 Cerberus<br/><i>credential broker</i><br/>request → lease"]
    end

    subgraph agents["The ten domain agents"]
        A["Argus · Lethe · Hermes<br/>Hephaestus · Aegis · Moira<br/>Mnemosyne · Clio · Themis · Eris"]
    end

    subgraph conn["Connectors — MCP process boundary"]
        K8S["Kubernetes<br/><i>Go</i>"]
        PY["Prometheus · Loki · Alertmanager<br/>GitLab · GitHub · Litmus<br/><i>Python</i>"]
    end

    subgraph target["Your systems"]
        SYS["Clusters · metrics · logs · pipelines"]
    end

    OPS <--> DASH
    DASH <--> AGUI
    AGUI <--> ZEUS

    ZEUS --> A
    ZEUS --> GUARD
    A -.->|"declares<br/>ModelRequirements"| DELPHI
    A -.->|"requests capability<br/>never a secret"| CERB
    A --> conn

    GUARD -->|"approval surface"| AGUI
    CERB -->|"access request<br/>surface"| AGUI
    CERB -.->|"lease"| conn

    conn --> SYS

    classDef infraStyle fill:#1e293b,stroke:#64748b,color:#e2e8f0
    classDef brainStyle fill:#312e81,stroke:#6366f1,color:#e0e7ff
    class DELPHI,CERB infraStyle
    class ZEUS,GUARD brainStyle
```

Three rules hold that diagram together:

1. **Agents never name a model.** They declare requirements; Delphi resolves.
   Swapping providers is a settings change, not an eleven-file edit.
   ([ADR 0004](docs/adr/0004-llm-provider-abstraction.md))
2. **Agents never hold credentials.** They request a capability; Cerberus mints a
   lease bound to one connector and one investigation; the connector redeems it.
   A secret in an agent's context would enter a prompt — an unauditable,
   unrevocable exfiltration path.
   ([ADR 0005](docs/adr/0005-credential-brokering.md))
3. **Agent-generated UI is untrusted data, not code.** Rendered from a closed
   allowlist; no HTML, no script, no agent-supplied URLs.
   ([ADR 0006](docs/adr/0006-agentic-ui-protocols.md))

[ARCHITECTURE.md](ARCHITECTURE.md) has the layer model and the three flows.

## Languages

| Language | Owns | Why |
|---|---|---|
| **Python 3.12** | `core/`, `agents/`, `api/`, `simulator/`, most connectors | The agent and LLM ecosystem. Pydantic v2 defines every shape once. |
| **Go 1.23** | `pkg/`, `connectors/kubernetes/`, `cmd/` | `client-go` is the only first-class Kubernetes client; single static binaries for a CLI and a sidecar. |
| **TypeScript** | `dashboard/` — and nowhere else | Next.js 15 App Router. |

`core/contracts/` is the source of truth. Go structs and TypeScript types are
**generated** from it — hand-writing a mirrored type in either is forbidden, and
a test enforces it.

## Quickstart

Needs Python 3.12 + [uv](https://docs.astral.sh/uv/), Go 1.23, Node 22+ with
pnpm, Docker, and — for the deploy checks — Helm and Terraform.

```bash
git clone https://github.com/simootaz/pantheon-aiops.git
cd pantheon-aiops

make install          # uv sync, git hooks, dashboard deps

make lint typecheck test        # Python: ruff, mypy --strict, pytest
make lint-go test-go            # Go: vet, golangci-lint, build, test
make lint-ts test-ts            # TypeScript: biome, tsc, vitest
make codegen-verify             # fail if generated output has drifted
```

Bring up the datastores, object storage and a local model runtime — **no API
keys required**:

```bash
make up PROFILE=llm-local
#   API            http://localhost:8000
#   MinIO console  http://localhost:9001
```

`make help` lists every target.

> `pnpm` is installed globally via npm rather than corepack, and its version is
> pinned once as `packageManager` in `dashboard/package.json` — CI reads it from
> there, so local and CI cannot drift.

## Documentation

| | |
|---|---|
| [docs/REPOSITORY_MAP.md](docs/REPOSITORY_MAP.md) | **Read first.** Every directory, where things go, and the structure changelog |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layers, the three flows, the contract pipeline |
| [ROADMAP.md](ROADMAP.md) | Phases 0–7 and every deferred decision |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git Flow, codegen rules, guard philosophy |
| [docs/adr/](docs/adr/README.md) | Six decision records |
| [docs/guard-verification.md](docs/guard-verification.md) | How every guard was verified, and the ones that failed |

## Licence

[Apache 2.0](LICENSE).
