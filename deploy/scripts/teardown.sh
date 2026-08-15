#!/usr/bin/env bash
# Tear down the local stack and remove its volumes.
#
# Phase: 6 - Go Port & Platform Binaries
#
# Destructive: this deletes Postgres data and every MinIO bucket.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../compose"

if [[ "${1:-}" != "--yes" ]]; then
  echo "teardown: this deletes all local Pantheon data (Postgres + MinIO)."
  echo "          re-run with --yes to confirm."
  exit 1
fi

docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile llm-local down --volumes --remove-orphans

echo "teardown: done"
