# Investigation Agent

LLM **copilot** for investigations: tool-use loop against Case API, Graph Service, Decision API, and optional knowledge/RAG. Ships deterministic **evidence summary** and export paths for review workflows.

**Port:** 8006  
**Framework:** Python / FastAPI

---

## Highlights

| Concern | Entry point |
|---------|-------------|
| Chat (sync / SSE) | `POST /v1/chat`, `POST /v1/chat/stream` |
| Evidence summary (OSS #40) | `POST /v1/evidence/summary` — no LLM; structured `citations[].resolves_to`, `next_actions`, optional typology drivers |
| Operator checklist | `GET /v1/setup`, `GET /v1/ready`, `GET /v1/health` |
| Integration contract | `GET /v1/integration` |
| Trust / ops data source | Console strip calls Decision API **`GET /v1/ops/evaluation-posture`** + **`GET /v1/slo`** (not this service); see [API Reference — Trust / ops readiness](../api-reference.md#trust-ops-readiness) |

!!! note "Contracts & guides"

    OpenAPI: `contracts/openapi/investigation-agent.yaml`  
    [Feature data flows](../guides/feature-data-flows.md) · [intended use](../guides/investigation-agent-intended-use-and-data-flows.md) · [LLM data flow](../guides/investigation-agent-llm-data-flow.md) · [honesty](../honesty.md)

---

## Configuration

Requires **`OPENAI_API_KEY`** (or compatible base URL) for LLM rounds. Optional upstreams: **`CASE_API_URL`**, **`GRAPH_SERVICE_URL`**, **`DECISION_API_URL`**. Production hardening: **`infra/deploy/docker-compose.production-hardening.yml`**, `COPILOT_PRODUCTION_MODE`, and related envs — see investigation-agent README under `services/`.
