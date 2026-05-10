# Tarka v2 stack automation (Compose + local ML tooling).
# Run targets from the repository root.
#
# Compose: defaults to ``docker compose`` (Docker Compose V2). To use the legacy
# standalone binary: ``make build COMPOSE_CMD=docker-compose``.

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMPOSE_CMD ?= docker compose
COMPOSE_FILE ?= docker-compose.streams-ai.yml
COMPOSE := $(COMPOSE_CMD) -f $(COMPOSE_FILE)

MODEL_PATH := $(ROOT)/services/ml_sidecar/models/baseline_fraud_v1.onnx

.PHONY: build up down logs audit test-ml train-model verify-model help

help:
	@echo "Targets: build up down logs audit test-ml train-model verify-model"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

audit:
	cd "$(ROOT)/services/core_v2" && ruff check .
	cd "$(ROOT)/services/core_v2" && python3 -m pytest tests/ -q

test-ml: verify-model
	cd "$(ROOT)/services/ml_sidecar" && python3 -c "\
from onnx_engine import FraudPredictor; \
p = FraudPredictor(); \
score = p.predict([100.0, 1.0, 2.0, 50.0, 12.0]); \
print('ML inference smoke OK', score)"

train-model:
	cd "$(ROOT)" && python3 scripts/train_baseline_xgboost.py

verify-model:
	cd "$(ROOT)" && export TARKA_ONNX_MODEL="$(MODEL_PATH)" && python3 -c "import os, onnxruntime as ort; ort.InferenceSession(os.environ['TARKA_ONNX_MODEL']); print('Model Validated: OK')"
