#!/usr/bin/env bash
# Post-deploy smoke test: assert the stack answers.
#
# Phase: 6 - Go Port & Platform Binaries
set -euo pipefail

BASE_URL="${PANTHEON_BASE_URL:-http://localhost:8000}"

echo "smoke-test: GET ${BASE_URL}/health"
status="$(curl -fsS -o /tmp/pantheon-health.json -w '%{http_code}' "${BASE_URL}/health")"

if [[ "$status" != "200" ]]; then
  echo "smoke-test: expected 200, got ${status}" >&2
  exit 1
fi

grep -q '"status":"ok"' /tmp/pantheon-health.json || {
  echo "smoke-test: unexpected body:" >&2
  cat /tmp/pantheon-health.json >&2
  exit 1
}

echo "smoke-test: ok"
# TODO: Phase 6 - assert MinIO buckets exist and Delphi resolves a model
