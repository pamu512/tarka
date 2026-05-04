# Service ports and OpenAPI index

Single reference for **default HTTP ports**, **Docker Compose service names** (internal DNS), and **`contracts/openapi`** specs. Aligns with `deploy/docker-compose.yml`, Helm `values.yaml`, and the Components table in the repo root `README.md`.

## Macroservices (preferred Compose / Helm layout)

| Logical surface | Host port (typical) | Compose service | Mount prefix (in-process) | Notes |
|-----------------|---------------------|-----------------|---------------------------|--------|
| **Core API** (decision + case) | 8000 | `core-api` | `/decisions`, `/cases` | Single Uvicorn; probes use `/decisions/v1/ready`. OpenAPI: [decision-api.yaml](../../../contracts/openapi/decision-api.yaml), [case-api.yaml](../../../contracts/openapi/case-api.yaml) — call with mount prefix. |
| **Signal API** (feature + ML + calibration + counter + location) | 8004 | `signal-api` | `/features`, `/ml`, `/calibration`, `/counters`, `/location` | OpenAPI: [feature-service.yaml](../../../contracts/openapi/feature-service.yaml), [ml-scoring.yaml](../../../contracts/openapi/ml-scoring.yaml), etc. — add mount prefix when using the macroservice. |
| **Data plane** (ingest + analytics) | 8007 | `data-plane` | `/v1/…` (ingest + analytics routes on one port) | `streaming` / `analytics` / `full` profiles; NATS + optional ClickHouse. |

## Other application services

| Logical service | Host port (typical) | Compose service name | OpenAPI spec | Notes |
|-----------------|---------------------|----------------------|--------------|--------|
| Graph Service | 8001 | `graph-service` | [graph-service.yaml](../../../contracts/openapi/graph-service.yaml) | Neo4j-backed; requires `graph` profile |
| Integration ingress | 8003 | `integration-ingress` | [integration-ingress.yaml](../../../contracts/openapi/integration-ingress.yaml) | `integration` profile; also **`docker-compose.lite.yml`** |
| Investigation agent | 8006 | `investigation-agent` | [investigation-agent.yaml](../../../contracts/openapi/investigation-agent.yaml) | `agent` profile; Slack/Teams/Lark **chat_bridge** embedded under **`/v1/chat/…`** (not a separate `:8009` container in default compose) |
| GraphQL gateway | 8010 | `graphql-gateway` | _(no REST OpenAPI in repo — GraphQL schema is code-first; see [API Reference — GraphQL Gateway](../api-reference.md#graphql-gateway))_ | `gateway` profile; defaults target **`http://core-api:8000/decisions`** and **`/cases`**. |
| Frontend (nginx) | 3000 → container 80 | `frontend` | _(UI)_ | `ui` / `full` profile |

Standalone Python packages under `services/decision-api`, `services/case-api`, `services/feature-service`, etc. remain the **source modules** for the macroservices; CI and local `tarka.py dev <legacy-name>` may still target them individually.

## Internal URLs (Docker network)

From any container on the default Compose network, use **service name + container listen port** (same as host-mapped port in our files):

- `http://core-api:8000/decisions` — decision evaluate, audit, rules (path prefix required)
- `http://core-api:8000/cases` — case workflows, disputes (path prefix required)
- `http://signal-api:8004/features`, `.../ml`, `.../calibration`, `.../counters`, `.../location`
- `http://graph-service:8001`
- `http://investigation-agent:8006`
- `http://data-plane:8007`
- `http://graphql-gateway:8010`

**In-process case → decision:** `core-api` sets `DECISION_API_URL=http://127.0.0.1:8000/decisions` for the case sub-app (see `deploy/docker-compose.yml`).

**Investigation agent:** `CASE_API_URL=http://core-api:8000/cases`, `DECISION_API_URL=http://core-api:8000/decisions`, optional `GRAPH_SERVICE_URL`.

**Data plane → decisions:** `DECISION_API_URL=http://core-api:8000/decisions`.

## Helm (Kubernetes)

Service names follow `{{ release-name }}-<component>` (see `deploy/helm/fraud-stack/templates/*.yaml`). Key toggles: **`coreApi`**, **`signalApi`**, **`dataPlane`**, **`graphqlGateway`**, etc. Ports default like the table unless overridden in `values.yaml`.

Templates wire **`DECISION_API_URL`** / **`CASE_API_URL`** with **`/decisions`** and **`/cases`** suffixes where consumers expect the consolidated **core-api** service.

## Localhost without Docker

Use `http://localhost:<port>` with the same path prefixes as in Docker (e.g. `http://localhost:8000/decisions/v1/health`).

## Keeping this file accurate

When adding a service or changing a port:

1. Update `deploy/docker-compose.yml` (and `lite` / `sandbox` if applicable).
2. Update this page and the root `README.md` Components table.
3. Add or adjust `contracts/openapi/<service>.yaml` `servers` if the service is contract-published.
