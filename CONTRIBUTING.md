# Contributing to Pantheon

> **Phase: 0 - Scaffold & Tooling.** The full guide is written on branch
> `feature/docs-baseline`. The two sections below are binding now.

Read [CLAUDE.md](CLAUDE.md) first — it is the map of this repository.

---

## Git Flow

`main` and `develop` already exist.

- **Never commit directly to `develop` or `main`.**
- Start every unit of work on a feature branch:
  ```bash
  git checkout develop && git pull && git checkout -b feature/<name>
  ```
- Use **conventional commits**: `feat:`, `chore:`, `docs:`, `test:`, `build:`,
  `refactor:`, `style:`.
- Merge only when the feature is complete **and its checks pass**:
  ```bash
  git checkout develop && git merge --no-ff feature/<name> && git branch -d feature/<name>
  ```

### CLAUDE.md is part of every structural change

If you create, move, rename or delete a directory or a significant file, update
`CLAUDE.md` **in the same commit** — the folder map, the "Where do I put X?"
table, and a new row in the structure changelog. A feature branch that changes
structure without touching `CLAUDE.md` is incomplete.

`tests/unit/test_repo_structure.py` enforces part of this automatically. **Extend
it on every branch that changes structure** — that is what keeps the map from
being something we merely remember to update.

---

## Codegen rules

`core/contracts/` is the single source of truth. Go structs and TypeScript types
are **generated** from it.

> **Hand-writing a mirrored type in Go or TypeScript is forbidden.**

### The pipeline

```
core/contracts/*.py  (Pydantic v2)
        │  codegen/export_schemas.py
        ▼
core/contracts/export/pantheon.schema.json     ← one artifact, one drift surface
        ├── codegen/gen_go.sh  → pkg/contracts/contracts.gen.go
        └── codegen/gen_ts.sh  → dashboard/types/generated/contracts.ts
```

Both generators consume the **JSON Schema**, not the FastAPI OpenAPI document.
See [ADR 0002](docs/adr/0002-codegen-from-json-schema.md) for why. Endpoint
types (paths, params, status codes) arrive at Phase 1 as a separate additive
generator, `codegen/gen_ts_api.sh`.

### To change a shape

1. Edit the model in `core/contracts/`.
2. Add it to `EXPORTED_MODELS` in `core/contracts/__init__.py` if it is a new
   top-level model. Nested models are pulled in automatically.
3. Extend `ContractModel`, never `BaseModel` directly — contracts are closed
   (`extra="forbid"`), and Pydantic only emits `additionalProperties: false` for
   closed models. Without it the TypeScript generator silently reopens them with
   an index signature.
4. Run `make codegen`.
5. **Commit the contract change and the regenerated output together.**

### Never edit these by hand

- `core/contracts/export/`
- `pkg/contracts/`
- `dashboard/types/generated/`

`make codegen-verify` regenerates the chain into a temp directory and diffs it
against the committed copies. It runs in pre-commit and in CI, and fails on any
difference.

### Generator versions are pinned

`go-jsonschema` at `v0.24.1`, `json-schema-to-typescript` at `15.0.4`. Changing
a pin will change the generated output, so treat it as a real change: bump the
pin and commit the regenerated artifacts in the same commit.

<!-- TODO: Phase 0 - full contributing guide on branch feature/docs-baseline -->
