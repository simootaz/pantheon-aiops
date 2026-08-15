#!/usr/bin/env bash
# Generate TypeScript types from the exported JSON Schema into
# dashboard/types/generated/.
#
# Phase: 0 - Scaffold & Tooling
#
# Usage: gen_ts.sh [OUT_DIR] [SCHEMA_FILE]
#   OUT_DIR      defaults to dashboard/types/generated/
#   SCHEMA_FILE  defaults to the committed core/contracts/export/ schema
#
# Types come from the JSON Schema, NOT from the FastAPI OpenAPI document - see
# docs/adr/0002-codegen-from-json-schema.md. Endpoint-surface types (paths,
# params, status codes) are a separate additive generator at Phase 1.
#
# The generator version is pinned; see the note in gen_go.sh for why.
set -euo pipefail

JSON_SCHEMA_TO_TS_VERSION="15.0.4"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dashboard/types/generated}"
SCHEMA="${2:-$ROOT/core/contracts/export/pantheon.schema.json}"
OUT_FILE="$OUT_DIR/contracts.ts"

if [[ ! -f "$SCHEMA" ]]; then
  echo "gen_ts.sh: schema not found: $SCHEMA" >&2
  echo "           run 'make codegen' or 'python -m codegen.export_schemas' first" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

# json-schema-to-typescript keeps only the first line of a multi-line
# --bannerComment, which silently drops the DO-NOT-EDIT warning. Generate with
# no banner and prepend our own, which is fully under our control and stable
# byte-for-byte.
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

npx --yes "json-schema-to-typescript@${JSON_SCHEMA_TO_TS_VERSION}" \
  --input "$SCHEMA" \
  --output "$BODY" \
  --bannerComment ""

{
  printf '%s\n' \
    '/* eslint-disable */' \
    '/**' \
    ' * Generated from core/contracts/ by codegen/gen_ts.sh. DO NOT EDIT BY HAND.' \
    ' *' \
    ' * Source of truth: core/contracts/ (Pydantic v2), via' \
    ' * core/contracts/export/pantheon.schema.json. Regenerate with: make codegen' \
    ' */' \
    ''
  cat "$BODY"
} >"$OUT_FILE"

echo "gen_ts.sh: wrote ${OUT_FILE#"$ROOT/"}"
