# Service ports and OpenAPI index

Single reference for **default HTTP ports**, **Docker Compose service names** (internal DNS), and **`contracts/openapi`** specs. Aligns with `deploy/docker-compose.yml` and the Components table in the repo root `README.md`.

## Application services

| Logical service | Host port (typical) | Compose service name | OpenAPI spec | Notes |
|-----------------|---------------------|----------------------|--------------|--------|
| Decision API | 8000 | `decision-api` | [decision-api.yaml](../../../contracts/openapi/decision-api.yaml) | Core scoring, audit, replay, entity-velocity |
| Graph Service | 8001 | `graph-service` | [graph-service.yaml](../../../contracts/openapi/graph-service.yaml) | Neo4j-backed; requires `graph` profile |
| Case API | 8002 | `case-api` | [case-api.yaml](../../../contracts/openapi/case-api.yaml) | Cases, disputes, investigation label drafts |
| Integration ingress | 8003 | `integration-ingress` | [integration-ingress.yaml](../../../contracts/openapi/integration-ingress.yaml) | `integration` profile; also **`docker-compose.lite.yml`** |
| Feature service | 8004 | `feature-service` | [feature-service.yaml](../../../contracts/openapi/feature-service.yaml) | `ml` profile |
| ML scoring | 8005 | `ml-scoring` | [ml-scoring.yaml](../../../contracts/openapi/ml-scoring.yaml) | `ml` profile |
| Investigation agent | 8006 | `investigation-agent` | [investigation-agent.yaml](../../../contracts/openapi/investigation-agent.yaml) | `agent` profile; calls case + decision + graph |
| Calibration service | 8011 | `calibration-service` | [calibration-service.yaml](../../../contracts/openapi/calibration-service.yaml) | `full` profile; calibration registry + drift + confidence scoring |
| Counter service | 8012 | `counter-service` | [counter-service.yaml](../../../contracts/openapi/counter-service.yaml) | `full` profile; counter definitions + replay/parity APIs |
| Location service | 8013 | `location-service` | [location-service.yaml](../../../contracts/openapi/location-service.yaml) | `full` profile; location confidence + co-presence/impossible travel |
| Collaboration chat bridge | 8009 | `collaboration-chat-bridge` | [collaboration-chat-bridge.yaml](../../../contracts/openapi/collaboration-chat-bridge.yaml) | `collab` / `agent` / `full`; Slack / Teams / Lark → agent |
| Event ingest | 8007 | `event-ingest` | _(no contract in repo)_ | `streaming` profile |
| Analytics sink | 8008 | `analytics-sink` | _(no contract in repo)_ | `analytics` profile |
| GraphQL gateway | 8010 | `graphql-gateway` | _(no REST OpenAPI in repo — GraphQL schema is code-first; see [API Reference — GraphQL Gateway](../api-reference.md#graphql-gateway))_ | `gateway` profile |
| Frontend (nginx) | 3000 → container 80 | `frontend` | _(UI)_ | `ui` / `full` profile |

## Internal URLs (Docker network)

From any container on the default Compose network, use **service name + container listen port** (same as host-mapped port in our files):

- `http://decision-api:8000`
- `http://case-api:8002`
- `http://graph-service:8001`
- `http://investigation-agent:8006`
- `http://calibration-service:8011`
- `http://counter-service:8012`
- `http://location-service:8013`
- `http://collaboration-chat-bridge:8009`
- `http://graphql-gateway:8010`

**Case API → Decision API:** set `DECISION_API_URL=http://decision-api:8000` (see `deploy/docker-compose.yml`, `docker-compose.lite.yml`, `docker-compose.sandbox.yml`).

**Investigation agent:** set `CASE_API_URL`, `DECISION_API_URL`, optional `GRAPH_SERVICE_URL` to the same pattern.

## Helm (Kubernetes)

Service names follow `{{ release-name }}-<component>` (see `deploy/helm/fraud-stack/templates/*.yaml`). Ports match the table above unless overridden in `values.yaml` (e.g. `eventIngest.port`, `graphqlGateway.port`, `frontend.port`).

Env wiring is **not** all in `values.yaml`—templates inject URLs such as `DECISION_API_URL` when a dependency chart is enabled (e.g. case-api when `decisionApi.enabled`). See comments at the top of `values.yaml`.

## Localhost without Docker

Use `http://localhost:<port>` from the table. OpenAPI `servers.url` fields use these defaults for developer ergonomics.

## Keeping this file accurate

When adding a service or changing a port:

1. Update `deploy/docker-compose.yml` (and `lite` / `sandbox` if applicable).
2. Update this page and the root `README.md` Components table.
3. Add or adjust `contracts/openapi/<service>.yaml` `servers` if the service is contract-published.
