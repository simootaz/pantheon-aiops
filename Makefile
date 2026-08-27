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

.PHONY: help install dev sim test test-sim test-connectors test-alerts test-argus test-flow-one test-providers test-delphi test-go test-ts lint lint-go lint-ts \
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
# 500x, not 4320x. A tick costs two HTTP round trips whatever span it covers, so
# the ceiling is tick_seconds/cost - see simulator.runner.max_honest_speed, which
# a guard holds this default under. Defaulting to 4320x made the honest "fell
# behind" warning fire on every single run, and a warning that always fires is
# one nobody reads.
sim:
	@uv run pantheon-sim run $(or $(SCENARIO),bad_deploy_5xx) --speed $(or $(SPEED),500)

## test: run the Python test suite and the per-module coverage floor
test:
	@uv run pytest -m "not integration"
	@uv run python -m tests.coverage_floor

## test-sim: assert on the DATA the simulator produces against a live stack
# `make help` parses one "## name: text" line per target; a second ## line
# rendered as a row with no target name.
#
# PANTHEON_REQUIRE_STACK turns the fixture's skip into a failure. Without it an
# unreachable Loki makes all nine tests skip and pytest exit 0, so this target
# reports success having asserted nothing. That is not hypothetical - it
# happened on this machine, right after `make sim` loaded Loki with 240k lines.
#
# Named file, not the directory. This target ran `tests/integration` wholesale,
# so adding the connector and alert gates swept them in - and CI's simulator job
# starts only prometheus, loki and pushgateway, so they errored on a missing API
# while the simulator assertions themselves all passed. Each gate needs its own
# services, so each gets its own target.
test-sim:
	@echo "test-sim: needs the stack up; runs real scenarios, so it takes minutes."
	@PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_simulator_data.py -m integration --no-cov -v -s

## test-connectors: prove the connector path against a live stack
# Same require-stack discipline as test-sim: a skipped gate reads as a pass, and
# this one exists to prove a real query reaches a real Prometheus.
test-connectors:
	@PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_connector_path.py -m integration --no-cov -v

## test-delphi: prove the gateway reaches a real model, whichever one is configured
# Skips rather than fails when no API key is set: a developer who has not signed
# up for a third-party service has not broken anything, and a red gate that means
# "you did not sign up" trains people to ignore red gates.
test-delphi:
	@uv run pytest tests/integration/test_delphi_live.py -m integration --no-cov -v

## test-flow-one: prove flow 1 end to end - alert, plan, dispatch, detect, verdict
# The negative half is the point: a clean baseline must open NO investigation,
# and the positive half reads the result back on a second connection, because a
# test that reads through the object it wrote to cannot tell a dict from a database.
# The database credential is sourced from deploy/compose/.env rather than
# duplicated here: it is where the stack's own password is defined, and a second
# copy is a second thing to keep in step.
test-flow-one:
	@set -a; . deploy/compose/.env; set +a; 	 PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_flow_one.py 	   -m integration --no-cov -v

## test-providers: prove the Postgres provider store seals keys before they reach a column
# This is the gate that earns core/store/postgres_providers.py its coverage-floor
# exemption. It reads the sealed_key column on a SECOND connection and asserts the
# plaintext is not in it - which is the one claim a unit test cannot make, because a
# unit test reads the value back through the object that sealed it.
test-providers:
	@set -a; . deploy/compose/.env; set +a; 	 PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_provider_store.py 	   -m integration --no-cov -v

## test-argus: prove Argus detects each scenario and stays silent on a clean baseline
# The negative case runs three times. A detector that fires on everything passes
# every positive test, and one clean run is one sample.
test-argus:
	@PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_argus_detection_flow.py -m integration --no-cov -v

## test-alerts: prove flow 1 - a scenario fires its alert, baseline fires none
# The negative case is the point: a rule that fires on everything passes every
# positive test and is worse than no rule.
test-alerts:
	@PANTHEON_REQUIRE_STACK=1 uv run pytest tests/integration/test_alert_flow.py -m integration --no-cov -v

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
