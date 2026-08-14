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
	@echo "install: not wired yet - branch feature/python-tooling"; exit 1

## dev: run the API and worker locally with reload
dev:
	@echo "dev: not wired yet - branch feature/python-tooling"; exit 1

## sim: run a simulator scenario against the local stack
sim:
	@echo "sim: not wired yet - branch feature/python-tooling"; exit 1

## test: run the Python test suite
test:
	@echo "test: not wired yet - branch feature/python-tooling"; exit 1

## test-go: build and test every Go module in the workspace
test-go:
	@$(GO_MODULE_DIRS) | while IFS= read -r dir; do \
		echo "--- $$dir"; \
		( cd "$$dir" && go build ./... && go test ./... ) || exit 1; \
	done

## test-ts: run the dashboard test suite
test-ts:
	@echo "test-ts: not wired yet - branch feature/dashboard-scaffold"; exit 1

## lint: lint and format-check Python
lint:
	@echo "lint: not wired yet - branch feature/python-tooling"; exit 1

## lint-go: vet and golangci-lint every Go module in the workspace
lint-go:
	@root="$$(pwd)"; $(GO_MODULE_DIRS) | while IFS= read -r dir; do \
		echo "--- $$dir"; \
		( cd "$$dir" && go vet ./... && golangci-lint run --config "$$root/.golangci.yml" ./... ) || exit 1; \
	done

## lint-ts: run biome against the dashboard
lint-ts:
	@echo "lint-ts: not wired yet - branch feature/dashboard-scaffold"; exit 1

## typecheck: run mypy --strict over the Python tree
typecheck:
	@echo "typecheck: not wired yet - branch feature/python-tooling"; exit 1

## codegen: regenerate JSON Schema, Go structs and TypeScript types
codegen:
	@echo "codegen: not wired yet - branch feature/codegen-pipeline"; exit 1

## codegen-verify: fail if generated output has drifted from the contracts
codegen-verify:
	@echo "codegen-verify: not wired yet - branch feature/codegen-pipeline"; exit 1

## up: start the local Compose stack
up:
	@echo "up: not wired yet - branch feature/deploy-skeleton"; exit 1

## down: stop the local Compose stack
down:
	@echo "down: not wired yet - branch feature/deploy-skeleton"; exit 1

## clean: remove build artifacts and tooling caches
clean:
	@rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage coverage.xml
	@rm -rf dist build *.egg-info bin
	@rm -rf dashboard/.next dashboard/.turbo
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "clean: done"
