# Generated output - do not edit by hand

Go structs generated from `core/contracts/export/pantheon.schema.json` by
`codegen/gen_go.sh`, using `go-jsonschema` pinned to v0.24.1.

`contracts.gen.go` is overwritten on every run. Hand edits are detected by
`codegen/verify.sh` and fail CI and pre-commit.

Regenerate with `make codegen`.

## Why this lives in `pkg/`, not in a connector

These structs are shared by every Go consumer. Putting them inside
`connectors/kubernetes/pkg/contracts/` would mean a second Go connector had to
import the Kubernetes connector's module just to name a `Finding` - so `pkg/`
it is. See [ADR 0002](../../docs/adr/0002-codegen-from-json-schema.md).

## Known limitation: the event union

`EventEnvelope.Event` is generated as `interface{}`. Go has no sum types, and
the generator will not invent one. Narrow it by hand at the call site until
Phase 6 adds typed accessors.

_Phase: 0 - Scaffold & Tooling_
