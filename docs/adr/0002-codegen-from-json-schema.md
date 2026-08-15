# ADR 0002 — Codegen from JSON Schema, not from OpenAPI

- **Status:** Accepted
- **Date:** 2026-08-15
- **Decided on branch:** `feature/codegen-pipeline`
- **Supersedes:** the original Phase 0 spec, which said `gen_ts.sh` should
  consume the FastAPI OpenAPI document

## Context

`core/contracts/` is the single source of truth. Go structs and TypeScript types
are generated from it; hand-writing a mirrored type in either language is
forbidden. The open question was *which artifact* the generators consume.

The original spec said Go generates from JSON Schema and TypeScript generates
from the FastAPI OpenAPI document. That would have given the two languages
different inputs.

## Decision

**Both generators consume the same artifact: the JSON Schema exported from
`core/contracts/`.**

```
core/contracts/*.py  (Pydantic v2, source of truth)
        │
        │  codegen/export_schemas.py
        ▼
core/contracts/export/pantheon.schema.json      ← the one artifact
        │
        ├── codegen/gen_go.sh  → pkg/contracts/contracts.gen.go
        └── codegen/gen_ts.sh  → dashboard/types/generated/contracts.ts
                │
                └── codegen/verify.sh guards the whole chain
```

### Why not OpenAPI for TypeScript

1. **The dashboard needs domain types, not endpoint types.** It renders
   `Finding`, `Verdict` and `Investigation` regardless of which route happened
   to return them. OpenAPI-derived types are shaped by routing accidents — a
   model reachable from two endpoints, or from none, produces a different
   TypeScript surface than the model itself.
2. **One drift surface, not two.** Go and TypeScript consuming the same file
   means `verify.sh` guards one pipeline. Two inputs could diverge while both
   pipelines looked green — the schema and the OpenAPI document can disagree
   about the same model, and nothing would catch it.
3. **A health-route OpenAPI contains no domain models.** At the time of this
   decision `api/main.py` has no app at all. Generating from OpenAPI now would
   verify nothing real, which is worse than not generating.

### Endpoint-surface types are a separate, additive generator

This decision does **not** say OpenAPI types are worthless. Paths, query
parameters, request bodies and status codes are real and the dashboard's API
client will want them — they are simply a *different* concern from domain
shapes.

They arrive at **Phase 1** as `codegen/gen_ts_api.sh`, additive and independent:
it will emit the endpoint surface alongside — never on top of — the domain types
this ADR governs. Domain types keep coming from JSON Schema.

## Tooling

| Stage | Tool | Pinned at |
|---|---|---|
| Pydantic → JSON Schema | `pydantic.json_schema.models_json_schema` | `pydantic>=2.9` |
| JSON Schema → Go | `github.com/atombender/go-jsonschema` | `v0.24.1` |
| JSON Schema → TypeScript | `json-schema-to-typescript` | `15.0.4` |

**Versions are pinned deliberately.** `verify.sh` diffs regenerated output
against the committed copy. An unpinned generator changes its output when the
tool updates, which is indistinguishable from a real contract change — and a
drift detector that cries wolf is a drift detector everyone learns to ignore.

### Why two tools rather than one

`quicktype` can emit both Go and TypeScript from one schema, which looked
attractive: one tool, one interpretation. It was rejected after testing.

**quicktype flattens discriminated unions.** Given the four-variant `Event`
union it produced a single merged struct carrying the union of all variants'
fields, in both languages. That type can represent states no valid event can
occupy — `investigation_started` carrying a `verdict`. A generated type that
admits invalid states is worse than a weak one, because it looks precise.

The specialist tools were kept instead. Note that "one tool" was never the
principle — **one artifact** is. Two generators reading one schema is still one
drift surface.

### Known limitation: the event union in Go

`json-schema-to-typescript` emits the union correctly:

```ts
export type Event = InvestigationStartedEvent | FindingProducedEvent
                  | VerdictReadyEvent | ApprovalRequestedEvent;
```

`go-jsonschema` emits `Event interface{}`. **Go has no sum types**, and the
generator will not invent an encoding for one. This is accepted: `interface{}`
is unhelpful but honest, where quicktype's merged struct was actively wrong.
Callers narrow on the `type` discriminator by hand. Phase 6 may add
hand-written typed accessors *beside* the generated file — never inside it.

## Why the Go output lives in `pkg/contracts/`

The spec offered `pkg/mcpserver/contracts/` or the Kubernetes connector's
`pkg/contracts/`. Both were rejected in favour of a third option, its own module
at `pkg/contracts/`:

- **Not inside a connector.** `connectors/kubernetes/pkg/contracts/` would force
  a second Go connector to import the *Kubernetes connector's module* just to
  name a `Finding`. That coupling gets worse with every connector added.
- **Not inside `pkg/mcpserver/`.** Contracts are domain shapes; `mcpserver` is
  transport scaffolding. A future Go component that needs `Verdict` but not an
  MCP server should not drag one in.
- **`pkg/` is already the established home** for shared Go libraries
  ([ADR-adjacent: `feature/go-base-relocation`](../REPOSITORY_MAP.md#go-layout-and-how-to-build-it)),
  and it mirrors `core/contracts/` (Python) and `dashboard/types/generated/`
  (TypeScript).

`connectors/kubernetes/pkg/` was deleted as part of this branch.

## Consequences

**Good**

- One artifact, one drift surface, one verifier.
- Domain types are stable against routing changes.
- `verify.sh` runs in pre-commit and CI, and has been **observed failing** on
  planted drift at all three stages — not merely assumed to work.

**Costs**

- Two generator toolchains to keep pinned and updated.
- The Go event union is untyped until someone writes accessors by hand.
- Regenerating requires Python, Go and Node all present. CI installs all three
  anyway.

## Verification

The drift detector was tested by planting deliberate drift and confirming
failure, then reverting:

| Scenario | Expected | Observed |
|---|---|---|
| Clean tree | 0 | 0 |
| Contract changed, not regenerated | non-zero | 1 |
| Generated Go hand-edited | non-zero | 1 |
| Generated TypeScript hand-edited | non-zero | 1 |

The first run of this exercise found a real bug in `export_schemas.py`, which
crashed when writing outside the repo root and so made `verify.sh` fail
unconditionally — a false red that would have masked every future true one.
