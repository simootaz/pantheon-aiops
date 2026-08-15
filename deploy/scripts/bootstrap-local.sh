#!/usr/bin/env bash
# Bring up a complete local Pantheon stack from a fresh clone.
#
# Phase: 6 - Go Port & Platform Binaries
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../compose"

if [[ ! -f .env ]]; then
  echo "bootstrap-local: creating compose/.env from .env.example"
  cp .env.example .env
fi

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.dev.yml"

echo "bootstrap-local: starting datastores and object storage"
$COMPOSE up -d postgres redis minio

echo "bootstrap-local: creating buckets"
$COMPOSE up minio-init

echo "bootstrap-local: ready"
echo "  MinIO console : http://localhost:${MINIO_CONSOLE_PORT:-9001}"
echo "  Local models  : $COMPOSE --profile llm-local up -d ollama"
echo "  API           : make dev"
