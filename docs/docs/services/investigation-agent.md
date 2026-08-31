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
    [Feature data flows](../guides/feature-data-flows.md) · [intended use](../guides/investigation-agent-intended-use-and-data-flows.md) · [LLM data flow](../guides/investigation-agent-llm-data-flow.md)

---

## Configuration

Requires an OpenAI-compatible LLM endpoint for LLM rounds. BYO Azure OpenAI / Vertex / Bedrock / Claude / Qwen / in-cluster vLLM preferred; public `api.openai.com` is not the enterprise default. Set **`OPENAI_BASE_URL`** + **`OPENAI_API_KEY`** (or compatible). Optional upstreams: **`CASE_API_URL`**, **`GRAPH_SERVICE_URL`**, **`DECISION_API_URL`**. Production hardening: **`infra/deploy/docker-compose.production-hardening.yml`**, `COPILOT_PRODUCTION_MODE`, and related envs — see investigation-agent README under `services/`.

### Durable store (HA)

Default is process-local SQLite under `INVESTIGATION_DATA_DIR` (four files: RAG, feedback, agent runs, turn reviews). That cannot HA: Helm `dataPersistence.mode=local-sqlite` fails render when `replicaCount > 1`.

Set `INVESTIGATION_STORE=postgres` and `INVESTIGATION_DATABASE_URL` or `DATABASE_URL`. The four stores and batch/job blobs share schema `investigation_agent` on the same Postgres the stack already uses. Missing URL is fail-closed (startup / first use / `/v1/ready` 503). Helm `dataPersistence.mode=postgres` injects those env vars the same way core-api gets `DATABASE_URL`, allows `replicaCount > 1`, uses RollingUpdate, and does not require an RWO sqlite PVC.

Multi-replica requires postgres mode including batches.

`prod-on-k8s` enables the agent with `mode: postgres` and `replicaCount: 2` against the overlay's required external Postgres. Helm prod also sets `COPILOT_PRODUCTION_MODE` (same Python lock as the compose hardening overlay) so `/v1/chat` is not network-open.
