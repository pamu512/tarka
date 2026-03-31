# Contributing to Tarka

Thank you for your interest in contributing to Tarka! This document covers everything you need to get started.

## Project Overview

Tarka is an open-source, modular fraud detection platform. The system follows a microservices architecture where each service is independently deployable and communicates over HTTP/REST.

### Architecture

```
SDK (Web/Android/iOS/Python) --> Decision API --> Redis (tags + scores)
                                     |                |
                                     +--> Rule Engine  |
                                     +--> ML Scoring   |
                                     +--> OPA (optional)
                                     +--> Graph Service --> Neo4j
                                     +--> Integration Ingress (KYC adapters)

Investigation UI --> Case API --> Graph Service
                       |
                  AI Agent (LLM tool-use)
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| `services/decision-api` | 8000 | Fraud scoring, attestation, rule + ML orchestration |
| `services/graph-service` | 8001 | Entity graph (Neo4j), tag storage on nodes |
| `services/case-api` | 8002 | Investigation cases, labels, comments, UI |
| `services/integration-ingress` | 8003 | KYC webhooks, adapter registry |
| `services/feature-service` | 8004 | Feature snapshot computation |
| `services/ml-scoring` | 8005 | ML inference (heuristic + ONNX) |
| `services/investigation-agent` | 8006 | AI copilot with LLM tool-use loop |
| `services/event-ingest` | 8007 | Event ingestion pipeline |
| `services/analytics-sink` | 8008 | Analytics and reporting sink |
| `services/graphql-gateway` | 8010 | GraphQL API aggregating all services |

### Shared Utilities

The `services/shared/` directory contains cross-cutting concerns used by multiple services:

- **`auth.py` / `auth_rbac.py`** — API key validation and role-based access control
- **`observability.py`** — Structured logging and metrics setup
- **`rate_limiter.py`** — Per-tenant rate limiting middleware
- **`audit_trail.py`** — Immutable audit log for compliance
- **`webhook_sender.py`** — Outbound webhook delivery with retries and DLQ

## Development Setup

### Prerequisites

- **Python 3.12+**
- **Docker** and **Docker Compose** (for running infrastructure and full-stack tests)
- **Git**

### Clone and Install

```bash
git clone https://github.com/your-org/tarka.git
cd tarka

# Install a specific service in development mode
cd services/decision-api
pip install -e ".[dev]"
```

Each service has its own `pyproject.toml` with a `[dev]` extras group containing test and lint dependencies.

### Running Infrastructure

```bash
cd deploy

# Core only (Decision API + Redis + Postgres)
docker compose --profile core up -d

# Full stack (all services)
cp .env.example .env
docker compose --profile full up -d
```

## Running Tests

Each service has a `tests/` directory. Run tests from the service root:

```bash
# Decision API
cd services/decision-api
pip install -e ".[dev]"
pytest --cov=decision_api tests/

# Case API
cd services/case-api
pip install -e ".[dev]"
pytest --cov=case_api tests/

# Python SDK
cd packages/fraud-sdk-python
pip install -e ".[dev]"
pytest --cov=fraud_stack_sdk tests/
```

Set `PYTHONPATH=src` if your IDE or runner doesn't resolve imports automatically.

## How to Add a New Service

1. Create a directory under `services/<your-service>/` with this layout:

   ```
   services/your-service/
   ├── pyproject.toml
   ├── Dockerfile
   └── src/
       └── your_service/
           ├── __init__.py
           ├── config.py
           └── main.py
   ```

2. In `pyproject.toml`, follow the existing pattern:

   ```toml
   [project]
   name = "tarka-your-service"
   version = "0.1.0"
   requires-python = ">=3.11"
   dependencies = [
     "fastapi>=0.115.0",
     "uvicorn[standard]>=0.32.0",
     "pydantic-settings>=2.6.0",
   ]

   [project.optional-dependencies]
   dev = ["pytest>=8.0", "pytest-asyncio>=0.24.0", "httpx>=0.28.0"]

   [build-system]
   requires = ["setuptools>=61"]
   build-backend = "setuptools.build_meta"

   [tool.setuptools.packages.find]
   where = ["src"]
   ```

3. In the `Dockerfile`, use the repo root as build context and copy `services/shared`:

   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /app
   COPY services/your-service/pyproject.toml /app/
   COPY services/your-service/src /app/src
   COPY services/shared /app/shared
   RUN pip install --no-cache-dir -e .
   ENV PYTHONPATH=/app/src
   CMD ["uvicorn", "your_service.main:app", "--host", "0.0.0.0", "--port", "80XX"]
   ```

4. Add the service to the Docker Compose profiles in `deploy/`.
5. Add the service to the CI matrix in `.github/workflows/ci.yml`.

## How to Add a New Rule Pack

Rules live in `services/decision-api/rules/` as JSON files. Each file contains an array of rule objects:

```json
[
  {
    "id": "my_rule_001",
    "description": "Flag high-value transactions from new accounts",
    "conditions": {
      "amount": { "$gt": 5000 },
      "account_age_days": { "$lt": 7 }
    },
    "score_delta": 30,
    "tags": ["high_value_new_account"]
  }
]
```

1. Create a new JSON file in `services/decision-api/rules/`.
2. The rule engine loads all `*.json` files from the `RULES_PATH` directory at startup.
3. Hot-reload rules via `POST /v1/admin/rules/reload` without restarting the service.

## How to Add a New KYC Adapter

KYC adapters live in `services/integration-ingress/`. To add a new provider:

1. Create an adapter module in `src/integration_ingress/adapters/your_provider.py`.
2. Implement the adapter interface:
   - Parse the incoming webhook payload
   - Normalize the result into the standard `KYCResult` schema
   - Return `approved`, `denied`, or `pending` with extracted entity data
3. Register the adapter in the adapter registry so it maps the provider name to your handler.
4. Add webhook endpoint configuration for the new provider.

## How to Add a New Workflow

Workflows live in `services/case-api/workflows/` as JSON files. They automate case management based on triggers:

```json
{
  "name": "auto_escalate_high_score",
  "trigger": "case_created",
  "conditions": {
    "priority": "critical"
  },
  "actions": [
    { "type": "set_field", "field": "assigned_team", "value": "fraud-ops" },
    { "type": "add_comment", "author": "workflow-engine", "body": "Auto-assigned to fraud-ops due to critical priority" }
  ]
}
```

1. Create a JSON file in `services/case-api/workflows/`.
2. Workflows are loaded at startup from the `WORKFLOWS_PATH` directory.
3. Hot-reload via `POST /v1/workflows/reload`.
4. Supported triggers: `case_created`, `case_updated`, `decision_deny`, `decision_review`.

## Code Style

- **Linter/formatter**: [Ruff](https://docs.astral.sh/ruff/) — run `ruff check .` and `ruff format --check .`
- **Type hints**: Required on all function signatures. Use `from __future__ import annotations` where needed.
- **Async**: All I/O-bound operations must be async. Use `httpx.AsyncClient` for HTTP calls.
- **Pydantic**: Use Pydantic v2 models for all request/response schemas. Use `pydantic-settings` for configuration.
- **Imports**: Keep imports sorted. Ruff handles this automatically.

## Pull Request Process

1. **Branch**: Create a feature branch from `main` (`feature/your-change` or `fix/your-bug`).
2. **Scope**: Keep PRs focused — one feature or fix per PR.
3. **Tests**: Add or update tests for any changed behavior. All tests must pass.
4. **Lint**: Ensure `ruff check .` and `ruff format --check .` pass with no errors.
5. **Description**: Write a clear PR description explaining *what* changed and *why*.
6. **Review**: At least one approval is required before merging.
7. **CI**: All CI checks (lint, test, Docker build) must be green.

### Commit Messages

Use concise, imperative-mood messages:

```
Add velocity-based rule pack for payment events
Fix race condition in tag merge when APOC unavailable
Update ML scoring to support ONNX Runtime 1.19
```

## License

This project is licensed under **AGPL-3.0**. By contributing, you agree that your contributions will be licensed under the same terms. See [LICENSE](LICENSE) for details.
