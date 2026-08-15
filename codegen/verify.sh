#!/usr/bin/env bash
# Fail if any generated artifact has drifted from core/contracts/.
#
# Phase: 0 - Scaffold & Tooling
#
# Regenerates the whole chain into a temp directory and diffs each artifact
# against the committed copy. Non-zero exit on any difference.
#
# The chain is regenerated end to end from the *freshly exported* schema, not
# from the committed one. That way a contract change that was never propagated
# is caught even when the committed schema is itself stale - checking each stage
# against the previous committed stage would let a stale pair agree with each
# other and both be wrong.
#
# Runs in pre-commit and in the codegen-check workflow.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/schema" "$TMP/go" "$TMP/ts"

FRESH_SCHEMA="$TMP/schema/pantheon.schema.json"
drifted=0

report() {
  echo "" >&2
  echo "DRIFT: $1" >&2
  echo "  committed: $2" >&2
  echo "  Run 'make codegen' and commit the result." >&2
  drifted=1
}

# --- stage 1: Pydantic -> JSON Schema ---------------------------------------
uv run python -m codegen.export_schemas --output "$TMP/schema" >/dev/null

if ! diff -u "core/contracts/export/pantheon.schema.json" "$FRESH_SCHEMA" >"$TMP/schema.diff" 2>&1; then
  report "JSON Schema is out of date with core/contracts/" "core/contracts/export/pantheon.schema.json"
  head -40 "$TMP/schema.diff" >&2
fi

# --- stage 2: JSON Schema -> Go ---------------------------------------------
bash "codegen/gen_go.sh" "$TMP/go" "$FRESH_SCHEMA" >/dev/null

if ! diff -u "pkg/contracts/contracts.gen.go" "$TMP/go/contracts.gen.go" >"$TMP/go.diff" 2>&1; then
  report "Go contracts are out of date" "pkg/contracts/contracts.gen.go"
  head -40 "$TMP/go.diff" >&2
fi

# --- stage 3: JSON Schema -> TypeScript -------------------------------------
bash "codegen/gen_ts.sh" "$TMP/ts" "$FRESH_SCHEMA" >/dev/null

if ! diff -u "dashboard/types/generated/contracts.ts" "$TMP/ts/contracts.ts" >"$TMP/ts.diff" 2>&1; then
  report "TypeScript contracts are out of date" "dashboard/types/generated/contracts.ts"
  head -40 "$TMP/ts.diff" >&2
fi

if [[ "$drifted" -ne 0 ]]; then
  echo "" >&2
  echo "verify.sh: generated output has drifted from core/contracts/" >&2
  exit 1
fi

echo "verify.sh: no drift - schema, Go and TypeScript all match core/contracts/"
