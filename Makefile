# Tarka desk automation (lite + fraud-desk compose).
# Run targets from the repository root.
#
# Compose: defaults to ``docker compose`` (Docker Compose V2). To use the legacy
# standalone binary: ``make build COMPOSE_CMD=docker-compose``.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMPOSE_CMD ?= docker compose
COMPOSE_FILE ?= infra/deploy/docker-compose.lite.yml
COMPOSE_DESK ?= infra/deploy/docker-compose.fraud-desk.yml
COMPOSE := $(COMPOSE_CMD) -f $(COMPOSE_FILE) -f $(COMPOSE_DESK)

.PHONY: build up down logs policy-check contract-check trend-tick demo doctor help

help:
	@echo "Targets: doctor demo build up down logs policy-check contract-check trend-tick"
	@echo "  doctor  preflight: Docker, day-1 ports, ~4 GB RAM"
	@echo "  demo    clone-and-run: lite+desk up, honest evaluate walk, one printed click"

# Day-1 preflight (no compose). See docs/docs/guides/clone-demo.md
doctor:
	python3 "$(ROOT)/scripts/oss/doctor.py"

# Public clone-and-run path (lite + fraud-desk + receipt walk). See docs/docs/guides/clone-demo.md
demo:
	bash "$(ROOT)/scripts/oss/up_desk.sh"

# Policy-as-code: JSON rule packs + v2 AST packs (+ optional OPA bundle lint).
policy-check:
	cd "$(ROOT)" && python3 infra/scripts/policy/validate_rule_packs.py
	cd "$(ROOT)" && python3 infra/scripts/policy/validate_opa_bundle.py

# Golden evaluate / device_context fixtures vs JSON Schema + EvaluateRequest.
contract-check:
	cd "$(ROOT)" && python3 infra/scripts/ci/validate_golden_evaluate_contracts.py

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

# Always-on trend tick (host loop). Override DECISION_API_URL / TREND_TICK_INTERVAL_S.
trend-tick:
	cd "$(ROOT)" && ./scripts/trend_tick_loop.sh
