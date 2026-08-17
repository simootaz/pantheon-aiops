# Pantheon developer entrypoints.
#
# Phase: 0 - Scaffold & Tooling
# Targets are wired branch by branch:
#   feature/python-tooling     -> install, dev, sim, test, lint, typecheck
#   feature/go-workspace       -> test-go, lint-go
#   feature/dashboard-scaffold -> test-ts, lint-ts
#   feature/codegen-pipeline   -> codegen, codegen-verify
#   feature/deploy-skeleton    -> up, down

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

# The repo root is not a Go module, so `go build ./...` cannot run from here.
# This lists the workspace module directories straight out of go.work, so adding
# a module to go.work is enough - nothing here needs updating.
GO_MODULE_DIRS := go list -m -f '{{.Dir}}'

.PHONY: help install dev sim test test-go test-ts lint lint-go lint-ts \
        typecheck codegen codegen-verify up down clean

## help: list every target
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed -e 's/## //' | awk -F':' '{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

## install: install all Python, Go and dashboard dependencies
install:
	@uv sync
	@uv run pre-commit install
	@cd dashboard && pnpm install --frozen-lockfile
	@echo "install: python (uv, 3.12), git hooks, and dashboard deps ready."
	@echo "         go modules have no external dependencies."

## dev: run the API locally with reload
dev:
	@uv run uvicorn api.main:create_app --factory --reload \
		--host $${PANTHEON_API_HOST:-127.0.0.1} --port $${PANTHEON_API_PORT:-8000}

## sim: run a simulator scenario (SCENARIO=name SPEED=n), e.g. make sim SCENARIO=memory_leak
sim:
	@uv run pantheon-sim run $(or $(SCENARIO),bad_deploy_5xx) --speed $(or $(SPEED),4320)

## test: run the Python test suite and the per-module coverage floor
test:
	@uv run pytest -m "not integration"
	@uv run python -m tests.coverage_floor

## test-sim: assert on the DATA the simulator produces, against a live stack
##           (needs `make up`; takes minutes, because it runs real scenarios)
test-sim:
	@uv run pytest tests/integration -m integration --no-cov -v -s

## test-go: build and test every Go module in the workspace
test-go:
	@$(GO_MODULE_DIRS) | while IFS= read -r dir; do \
		echo "--- $$dir"; \
		( cd "$$dir" && go build ./... && go test ./... ) || exit 1; \
	done

## test-ts: run the dashboard test suite
test-ts:
	@cd dashboard && pnpm run test

## lint: lint and format-check Python
lint:
	@uv run ruff check .
	@uv run ruff format --check .

## lint-go: vet and golangci-lint every Go module in the workspace
lint-go:
	@root="$$(pwd)"; $(GO_MODULE_DIRS) | while IFS= read -r dir; do \
		echo "--- $$dir"; \
		( cd "$$dir" && go vet ./... && golangci-lint run --config "$$root/.golangci.yml" ./... ) || exit 1; \
	done

## lint-ts: biome and tsc against the dashboard
lint-ts:
	@cd dashboard && pnpm run lint && pnpm run typecheck

## typecheck: run mypy --strict over the Python tree
typecheck:
	@uv run mypy

## codegen: regenerate JSON Schema, Go structs and TypeScript types
codegen:
	@uv run python -m codegen.export_schemas
	@bash codegen/gen_go.sh
	@bash codegen/gen_ts.sh

## codegen-verify: fail if generated output has drifted from the contracts
codegen-verify:
	@bash codegen/verify.sh

## up: start the local Compose stack (add PROFILE=llm-local for local models)
up:
	@cd deploy/compose && [ -f .env ] || cp .env.example .env
	@cd deploy/compose && docker compose -f docker-compose.yml -f docker-compose.dev.yml \
		$(if $(PROFILE),--profile $(PROFILE),) up -d
	@echo "up: API http://localhost:8000  MinIO console http://localhost:9001"

## down: stop the local Compose stack
down:
	@cd deploy/compose && docker compose -f docker-compose.yml -f docker-compose.dev.yml \
		--profile llm-local down

## clean: remove build artifacts and tooling caches
clean:
	@rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml
	@rm -rf dist build *.egg-info bin
	@rm -rf dashboard/.next dashboard/.turbo
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "clean: done"
