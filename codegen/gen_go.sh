#!/usr/bin/env bash
# Generate Go structs from the exported JSON Schema into pkg/contracts/.
#
# Phase: 0 - Scaffold & Tooling
#
# Usage: gen_go.sh [OUT_DIR] [SCHEMA_FILE]
#   OUT_DIR      defaults to pkg/contracts/
#   SCHEMA_FILE  defaults to the committed core/contracts/export/ schema
#
# codegen/verify.sh passes both so it can regenerate into a temp directory.
#
# The generator version is pinned. An unpinned generator would make verify.sh
# report drift whenever the tool changed, which is indistinguishable from a real
# contract change and would train everyone to ignore it.
set -euo pipefail

GO_JSONSCHEMA_VERSION="v0.24.1"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/pkg/contracts}"
SCHEMA="${2:-$ROOT/core/contracts/export/pantheon.schema.json}"
OUT_FILE="$OUT_DIR/contracts.gen.go"

if [[ ! -f "$SCHEMA" ]]; then
  echo "gen_go.sh: schema not found: $SCHEMA" >&2
  echo "           run 'make codegen' or 'python -m codegen.export_schemas' first" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

# go-jsonschema v0.24.1 cannot resolve internal "#/$defs/..." references when
# it is handed an ABSOLUTE input path - it fails with "unsupported $ref schema".
# A relative input path works. Absolute OUTPUT paths are fine, so resolve the
# output first, then run from the schema's own directory and pass the bare
# filename. Do not "simplify" this back to a single absolute argument.
SCHEMA_DIR="$(cd "$(dirname "$SCHEMA")" && pwd)"
SCHEMA_FILE="$(basename "$SCHEMA")"
OUT_ABS="$(cd "$OUT_DIR" && pwd)/$(basename "$OUT_FILE")"

(
  cd "$SCHEMA_DIR"
  go run "github.com/atombender/go-jsonschema@${GO_JSONSCHEMA_VERSION}" \
    --package contracts \
    --output "$OUT_ABS" \
    "$SCHEMA_FILE"
)

gofmt -w "$OUT_ABS"

echo "gen_go.sh: wrote ${OUT_FILE#"$ROOT/"}"
