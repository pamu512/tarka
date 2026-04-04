# Example: IOC enrichment + threat-actor style clustering (graph)

**Goal:** Combine **parallel OSINT** (IP / domain context) with a **live Neo4j-backed subgraph** for entity linkage. This matches a **cyber** use case (IOC pivoting); fraud teams can use the same pattern for **mule rings** or **shared devices**.

## Prerequisites

- **Neo4j** + **graph-service** + **integration-ingress** + **decision-api** (and optionally **case-api** / UI).

From repo root:

```bash
cd deploy
docker compose -f docker-compose.yml --profile core --profile graph --profile integration --profile cases --profile ui up -d --build
```

Ports: Decision **8000**, Graph **8001**, Case **8002**, Ingress **8003**, Frontend **3000**, Neo4j browser **7474**.

## 1. OSINT on an IOC

IP (Shodan / GreyNoise / AbuseIPDB / etc. — keys optional, see `.env.example`):

```bash
curl -s -X POST http://localhost:8003/v1/osint \
  -H "Content-Type: application/json" \
  -d '{"ip":"8.8.8.8","email":null,"phone":null,"domain":"example.com"}'
```

List configured sources:

```bash
curl -s http://localhost:8003/v1/osint/sources
```

## 2. Upsert graph entities (via graph-service API)

Use your deployment’s graph upsert endpoints (see `services/graph-service` OpenAPI or `contracts/openapi`) to create **User** / **IP** / **Domain** nodes and **RELATED_TO** edges. The **Graph Explorer** in the UI (`/graph`) visualizes neighborhoods when the backend is reachable.

## 3. Decision + graph context

Evaluate an event tied to the same **entity_id** you stored in Neo4j so Decision API can include **graph-derived** features when **`GRAPH_SERVICE_URL`** is set:

```bash
curl -s -X POST http://localhost:8000/v1/decisions/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "demo",
    "event_type": "custom",
    "entity_id": "ioc-entity-1",
    "payload": {"ioc_type": "ip", "value": "198.51.100.55", "severity_hint": "high"}
  }'
```

Inspect **`inference_context.top_signals`** and graph-related fields when the graph integration path is active.

## 4. MITRE-style tagging (roadmap)

Fine-grained **MITRE ATT&CK** labels are **not** fully wired as first-class fields in v1.1; track **`borrowed-from-OSS`** / typology issues for structured tactic/technique mapping. Until then, use **`tags`** on evaluate responses and case **`labels`** for analyst workflow.

## 5. Lite stack without Neo4j

Use **mock graph** behavior in the UI and OSINT-only curls from [sandbox-five-minute.md](../sandbox-five-minute.md) when you cannot run Neo4j.
