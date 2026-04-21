# Five-minute sandbox: Decision API, inference, OSINT, graph (mock UI)

Use this path when you want **copy-paste** steps that show **real `inference_context`** from the Decision API, **OSINT** aggregation from Integration Ingress, and **graph-style exploration**—with the **frontend** falling back to **rich mock data** when APIs are unreachable.

## Prerequisites

- Docker + Docker Compose

## Option A — Lite stack (builds from source, no Neo4j)

From the **repository root**:

```bash
docker compose -f deploy/docker-compose.lite.yml up -d --build
```

Wait for healthchecks (~30s), then:

### 1) Decision API — live `inference_context`

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate -H "Content-Type: application/json" -d '{"tenant_id":"demo","event_type":"payment","entity_id":"user-123","payload":{"amount":499,"event_count_5m":12,"event_count_1h":40,"event_count_24h":200}}'
```

You should see JSON with **`inference_context`** (tier, drivers, velocity fields, etc.) and **`recommended_action`**.

### 2) Integration Ingress — parallel OSINT envelope

```bash
curl -s -X POST http://localhost:8003/v1/osint -H "Content-Type: application/json" -d '{"ip":"8.8.8.8","email":null,"phone":null,"domain":null}'
```

Without commercial API keys, sources are skipped or use free tiers; the response still shows **aggregated structure** and partial signals.

### 3) Frontend — Case Detail explainability + graph (mock when API errors)

Open **http://localhost:3000**.

- **Cases → open a case** (use one that has a **trace ID**). In **Case detail**, the **Decision explainability** card shows v2-style **`inference_context`** from the Decision API audit when the gateway is up; if the request fails, the UI falls back to **mock audit payloads** in `frontend/src/api/mockData.ts`.
- **What to verify on Case detail** (v1.1.0 UI bar): **`confidence_tier`** and **schema version**; **velocity** row (**5m / 1h / 24h**); **colocation** and **impossible-travel** bars when those risks are **above zero**; **top drivers** (`driver_reasons`); **`recommended_action`**; **top_signals** chips when present.
- **Graph Explorer**: with **lite** compose, the live graph backend is **off**; use mock-driven views or start the **full** compose profile with Neo4j when you need a live graph.

### 4) Stop

```bash
docker compose -f deploy/docker-compose.lite.yml down
```

## Option B — Prebuilt images (sandbox compose)

For published images (may require registry access):

```bash
docker compose -f deploy/docker-compose.sandbox.yml up -d
```

Same `curl` targets; ports **8000**, **8003**, **3000** as in [service-ports.md](./service-ports.md).

## Option C — GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?hide_repo_select=true&ref=master&repo=pamu512%2Ftarka)

In the terminal:

```bash
docker compose -f deploy/docker-compose.lite.yml up -d --build
```

Forwarded ports (Codespaces / Dev Containers): see `.devcontainer/devcontainer.json` — defaults include **3000**, **8000**, **8002**, **8003**, **8005**, **8006**, **8009** (collaboration bridge), **8010** (GraphQL).

## AI copilot (optional)

With the **agent** profile on full compose, Investigation Agent listens on **8006** (`/v1/chat`). Configure `OPENAI_API_KEY` in the environment for LLM tool use; without it the agent returns an offline stub.

## See also

- [Service ports & OpenAPI](./service-ports.md)
- [Deployment](./deployment.md)
- [Ready-to-run examples](./examples/README.md) (payments + ONNX, bot defense, IOC + graph)
- [Shadow / simulation / A-B](./shadow-and-ab-testing.md)
- [Prometheus + Grafana add-on](../../../deploy/observability/README.md)
- [Latency benchmark script](../../../scripts/benchmarks/README.md)
- [LICENSE-DEPENDENCIES.md](../../../LICENSE-DEPENDENCIES.md) (Neo4j / AGPL)
- [Graph backend alternatives](./graph-backend-alternatives.md)
