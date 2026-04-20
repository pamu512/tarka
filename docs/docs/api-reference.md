# API Reference

Complete endpoint reference for all Tarka services. All services use JSON request/response bodies and return standard HTTP status codes.

**Authentication:** Set `API_KEYS` environment variable on any service. Clients must send `X-API-Key: <key>` header. Leave `API_KEYS` empty to disable authentication (development mode).

---

## Decision API — `:8000` {#decision-api}

OpenAPI: `contracts/openapi/decision-api.yaml`

### Core

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/slo` | Service SLO snapshot (availability, dependency checks, optional Redis/NATS signals) |
| `GET` | `/v1/ops/evaluation-posture` | Evaluation mode, deployment tier hint, `tenant_reliability_profile` (`TARKA_TENANT_RELIABILITY_PROFILE`), compliance prerequisites, predicate registry pin |
| `POST` | `/v1/decisions/evaluate` | Evaluate a fraud decision; optional header **`Idempotency-Key`** (or `idempotency-key`) — **required** when **`TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true`** (R3.2) |
| `GET` | `/v1/audit/{trace_id}` | Get audit record by trace ID (includes `counter_version`, `rule_pack_file`, `ml_model`, optional `etl_batch_id` from stored `payload_snapshot` / metadata) |
| `WebSocket` | `/v1/decisions/ws` | Live decision stream |

#### Trust / ops readiness (OSS #36) {#trust-ops-readiness}

The console **trust/ops readiness** strip (`frontend/src/components/AnalystReadinessBar.tsx`) calls **`GET /v1/ops/evaluation-posture`** (evaluation mode, deployment tier, `tenant_reliability_profile`, compliance degradation, typology count, predicate registry pin match, dependency rows, `last_rules_reload_at`) and **`GET /v1/slo`** (Redis/NATS connectivity hints). Deployment context: [Community vs Pro profiles](guides/deployment-profiles-community-vs-pro.md).

### Attestation

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/attestation/challenge` | Request attestation nonce |
| `POST` | `/v1/attestation/verify` | Verify attestation token |

### Rules

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/rules` | List all rule packs |
| `GET` | `/v1/rules/{filename}` | Get a specific rule pack |
| `POST` | `/v1/rules` | Create a new rule pack |
| `PUT` | `/v1/rules/{filename}` | Update a rule pack |
| `DELETE` | `/v1/rules/{filename}` | Delete a rule pack |
| `POST` | `/v1/rules/{filename}/rules` | Add a rule to a pack |
| `DELETE` | `/v1/rules/{filename}/rules/{rule_id}` | Remove a rule from a pack |
| `POST` | `/v1/admin/rules/reload` | Hot-reload rules, typologies, and predicate registry from disk |
| `GET` | `/v1/admin/typology/predicate-registry` | OSS #46 typology DSL catalog: `registry_id`, `version`, `predicates[]` (`id`, `description`, `when`); pin must match `predicate_registry_pin` in typology definitions |

### Replay

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/replay` | Backtest rules against historical events |

---

### `POST /v1/decisions/evaluate`

**Request:**

```json
{
  "tenant_id": "acme",
  "event_type": "payment",
  "entity_id": "user-42",
  "session_id": "sess-abc",
  "payload": {
    "amount": 499.99,
    "currency": "USD",
    "merchant": "store-1"
  },
  "device_context": {
    "device_id": "d-xxxx",
    "platform": "web",
    "signals": {
      "is_emulator": false,
      "is_vpn": false,
      "is_bot": false,
      "webdriver_detected": false,
      "headless_detected": false,
      "automation_detected": false,
      "timezone_geo_mismatch": false,
      "ip_is_proxy": false,
      "ip_is_datacenter": false
    },
    "attestation": null
  },
  "metadata": {}
}
```

**Response `200`:**

```json
{
  "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "decision": "allow",
  "score": 10.0,
  "tags": [],
  "rule_hits": [],
  "reasons": [],
  "ml_score": null
}
```

**Event types:** `login`, `payment`, `signup`, `device`, `session`, `custom`

---

### `POST /v1/attestation/challenge`

**Request:**

```json
{ "tenant_id": "acme" }
```

**Response `200`:**

```json
{ "nonce": "a3f8e2d1...", "expires_in": 300 }
```

---

### `POST /v1/attestation/verify`

**Request:**

```json
{ "nonce": "a3f8e2d1...", "token": "signed-token", "provider": "browser_challenge" }
```

**Response `200`:**

```json
{ "valid": true, "device_integrity": "browser" }
```

---

### `POST /v1/rules`

**Request:**

```json
{
  "name": "My Rule Pack",
  "rules": [
    {
      "id": "high_amount",
      "when": [{ "field": "amount", "op": "gte", "value": 5000 }],
      "tags": ["amount:high"],
      "score_delta": 15,
      "description": "Flag high amounts"
    }
  ],
  "tag_rules": []
}
```

**Response `201`:**

```json
{
  "file": "my_rule_pack.json",
  "pack": { "version": 1, "name": "My Rule Pack", "rules": [...], "tag_rules": [] }
}
```

---

### `POST /v1/replay`

**Request:**

```json
{
  "tenant_id": "acme",
  "rules_override": [
    {
      "id": "test_rule",
      "when": [{ "field": "amount", "op": "gte", "value": 1000 }],
      "tags": ["test:high"],
      "score_delta": 30
    }
  ],
  "limit": 500
}
```

**Response `200`:**

```json
{
  "tenant_id": "acme",
  "events_evaluated": 247,
  "decisions_changed": 18,
  "results": [
    {
      "trace_id": "...",
      "entity_id": "user-42",
      "event_type": "payment",
      "original_decision": "allow",
      "original_score": 10.0,
      "original_rule_hits": [],
      "new_decision": "review",
      "new_score": 40.0,
      "new_rule_hits": ["test_rule"],
      "new_tags": ["test:high"],
      "score_diff": 30.0,
      "decision_changed": true
    }
  ]
}
```

---

## Graph Service — `:8001` {#graph-service}

### Entities & Links

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `POST` | `/v1/entities` | Upsert entity node |
| `POST` | `/v1/entities/{external_id}/tags` | Update entity tags |
| `GET` | `/v1/entities/{external_id}/tags` | Get entity tags |
| `POST` | `/v1/links` | Create relationship between entities |
| `GET` | `/v1/subgraph` | Query entity neighborhood |

### Schema

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/schema/{tenant_id}` | Get tenant schema |
| `PUT` | `/v1/schema/{tenant_id}` | Update tenant schema |

### Analytics

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/analytics/communities` | Detect connected communities |
| `GET` | `/v1/analytics/risk-propagation` | Propagate risk from entity |
| `GET` | `/v1/analytics/shared-attributes` | Find entities sharing attributes |
| `GET` | `/v1/analytics/fraud-rings` | Detect cyclic fraud rings |
| `GET` | `/v1/analytics/entity-risk` | Composite entity risk score |

---

### `POST /v1/entities`

**Request:**

```json
{
  "tenant_id": "acme",
  "entity_type": "Account",
  "external_id": "user-42",
  "properties": { "email": "user@example.com" },
  "tags": ["sdk:vpn"]
}
```

**Response `200`:**

```json
{ "graph_id": "4:abc:0", "entity_type": "Account", "external_id": "user-42" }
```

**Entity types:** `Person`, `Account`, `Device`, `Payment`, `Document`, `Custom` (plus tenant-specific custom types).

---

### `POST /v1/links`

**Request:**

```json
{
  "tenant_id": "acme",
  "from_external_id": "user-42",
  "to_external_id": "device-abc",
  "relationship": "USED",
  "properties": { "trace_id": "..." }
}
```

**Response `200`:**

```json
{ "ok": true }
```

**Relationship types:** `USED`, `SHARED_WITH`, `REFERRED`, `KYC_VERIFIED_BY`, `OWNS`, `CUSTOM`, `RELATED` (plus tenant-specific custom types).

---

### `GET /v1/subgraph`

**Parameters:** `entity_id` (required), `tenant_id` (required), `depth` (1–5, default 2)

**Response `200`:**

```json
{
  "nodes": [
    { "id": "user-42", "labels": ["Account"], "properties": { "tags": ["sdk:vpn"] } }
  ],
  "edges": [
    { "from_id": "user-42", "to_id": "device-abc", "type": "USED", "properties": {} }
  ]
}
```

---

### `GET /v1/analytics/communities`

**Parameters:** `tenant_id` (required), `min_size` (default 3)

**Response `200`:**

```json
[
  {
    "community_id": 0,
    "member_count": 7,
    "member_ids": ["user-1", "user-2", "device-a"],
    "member_labels": ["Account", "Device"],
    "shared_attributes": ["sdk:vpn"]
  }
]
```

---

### `GET /v1/analytics/risk-propagation`

**Parameters:** `tenant_id` (required), `entity_id` (required), `depth` (1–5, default 3), `decay` (0–1, default 0.5)

**Response `200`:**

```json
[
  {
    "entity_id": "device-abc",
    "entity_labels": ["Device"],
    "propagated_risk_score": 50.0,
    "distance": 1,
    "path_description": "(user-42) -[USED]-> (device-abc)"
  }
]
```

---

### `GET /v1/analytics/shared-attributes`

**Parameters:** `tenant_id` (required), `attribute` (default `device_id`), `min_shared` (default 2)

**Response `200`:**

```json
[
  {
    "attribute": "device_id",
    "shared_value": "device-abc",
    "entity_ids": ["user-42", "user-99"],
    "group_size": 2
  }
]
```

---

### `GET /v1/analytics/fraud-rings`

**Parameters:** `tenant_id` (required), `min_size` (default 3)

**Response `200`:**

```json
[
  {
    "ring_members": ["user-1", "user-2", "device-shared"],
    "ring_size": 3,
    "relationships": ["USED", "SHARED_WITH", "USED"],
    "aggregate_tags": ["sdk:vpn", "fraud"]
  }
]
```

---

### `GET /v1/analytics/entity-risk`

**Parameters:** `tenant_id` (required), `entity_id` (required)

**Response `200`:**

```json
{
  "entity_id": "user-42",
  "risk_score": 55,
  "risk_factors": ["connected_flagged:2", "medium_community:4"],
  "connected_flagged_count": 2,
  "community_size": 4
}
```

---

## Case API — `:8002` {#case-api}

### Cases

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/cases` | List cases |
| `POST` | `/v1/cases` | Create case |
| `GET` | `/v1/cases/{case_id}` | Get case |
| `PATCH` | `/v1/cases/{case_id}` | Update case |
| `POST` | `/v1/cases/{case_id}/comments` | Add comment |
| `POST` | `/v1/cases/{case_id}/labels` | Apply labels |
| `GET` | `/v1/cases/{case_id}/graph` | Get case entity graph |
| `GET` | `/v1/cases/{case_id}/sla` | Get SLA status |
| `GET` | `/v1/cases/{case_id}/audit` | Get audit trail |
| `WebSocket` | `/v1/cases/ws` | Live case event stream |

### Workflows

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/workflows` | List workflows |
| `POST` | `/v1/workflows/reload` | Reload workflows from disk |
| `POST` | `/v1/workflows/trigger` | Manually trigger a workflow |

### Webhooks

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/webhooks/dlq` | View webhook dead letter queue |
| `POST` | `/v1/webhooks/dlq/{webhook_id}/retry` | Retry failed webhook |
| `POST` | `/v1/cases/{case_id}/sar/generate` | Generate SAR/STR report |
| `GET` | `/v1/cases/{case_id}/sar` | List SAR filings for a case |

---

### `POST /v1/cases`

**Request:**

```json
{
  "tenant_id": "acme",
  "title": "Suspicious payment",
  "entity_id": "user-42",
  "trace_id": "a1b2c3d4-...",
  "priority": "high"
}
```

**Response `201`:**

```json
{
  "id": "c1d2e3f4-...",
  "tenant_id": "acme",
  "title": "Suspicious payment",
  "entity_id": "user-42",
  "trace_id": "a1b2c3d4-...",
  "priority": "high",
  "status": "open",
  "labels": [],
  "assigned_team": null,
  "created_at": "2026-03-31T10:15:30",
  "updated_at": "2026-03-31T10:15:30"
}
```

---

### `PATCH /v1/cases/{case_id}`

**Request:**

```json
{ "status": "in_review", "priority": "critical", "assigned_team": "fraud-ops" }
```

---

### `GET /v1/cases/{case_id}/sla`

**Response `200`:**

```json
{
  "case_id": "c1d2e3f4-...",
  "priority": "high",
  "sla_deadline": "2026-03-31T14:15:30+00:00",
  "breached": false,
  "status": "open"
}
```

---

### `POST /v1/workflows/trigger`

**Request:**

```json
{
  "trigger": "decision_deny",
  "case": { "id": "c1d2e3f4-...", "priority": "high", "labels": [] },
  "decision": { "score": 92, "tags": ["sdk:bot"] }
}
```

**Response `200`:**

```json
{
  "actions_executed": [
    { "type": "set_priority", "priority": "critical" },
    { "type": "escalate" }
  ],
  "mutations": { "status": "escalated", "priority": "critical" }
}
```

---

## Integration Ingress — `:8003` {#integration-ingress}

Provider catalog, installs, connectivity tests, and **integration reliability scorecards** (per installed connection).

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/integrations/catalog` | List available integration providers |
| `GET` | `/v1/integrations/installed` | List tenant connections (`tenant_id` query) |
| `GET` | `/v1/integrations/readiness` | Category coverage score (`tenant_id`) |
| `GET` | `/v1/integrations/health-matrix` | Latest connectivity probe summary (`tenant_id`) |
| `GET` | `/v1/integrations/scorecards` | **Per-provider scores + connector quality** (`tenant_id`) — used by the Integrations UI |
| `POST` | `/v1/integrations/install` | Install / enable a provider |
| `POST` | `/v1/integrations/test-connectivity` | Run connectivity check |

OpenAPI: `contracts/openapi/integration-ingress.yaml`.

---

## Analytics Sink — `:8008` {#analytics-sink}

ClickHouse-backed analytics over decision events. Requires `X-API-Key` when the service is configured with `API_KEYS` (same pattern as other services).

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health (`clickhouse` availability) |
| `GET` | `/v1/analytics/decisions` | Recent decision rows (`tenant_id`, optional filters) |
| `GET` | `/v1/analytics/hourly` | Hourly aggregates (`tenant_id`, `days`) |
| `GET` | `/v1/analytics/top-entities` | Top entities by decision (`tenant_id`, `decision`, `days`) |
| `GET` | `/v1/analytics/scorecard` | **Decision scorecard JSON** — totals, per-decision mix, top rule hits (`tenant_id`, `days`) — used by Analytics UI and weekly export scripts |

OpenAPI: _not published under `contracts/openapi/` yet_ (this HTTP table is authoritative).

Weekly JSON export stub (N4.2): `scripts/analytics/export_weekly_scorecard_json.py`. Discussions publisher (OSS #53): `scripts/analytics/publish_scorecard_discussion.py`.

---

## ML Scoring — `:8005` {#ml-scoring}

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check (includes model status) |
| `POST` | `/v1/score` | Score features for fraud risk |
| `GET` | `/v1/models` | List all registered models |
| `GET` | `/v1/promotion-policy` | Active promotion gate policy JSON (OSS #37 / #52) |
| `GET` | `/v1/models/{name}/{version}/promotion-check` | Dry-run gate + `report` artifact without activating traffic |
| `POST` | `/v1/models/{name}/activate` | Activate a model version |
| `GET` | `/v1/models/{name}/stats` | Get model inference stats |

OpenAPI: `contracts/openapi/ml-scoring.yaml`. Policy files: `services/ml-scoring/rules/ml_promotion_policy_v1.json` (+ YAML twin for CI sync).

---

### `POST /v1/score`

**Request:**

```json
{
  "tenant_id": "acme",
  "entity_id": "user-42",
  "event_type": "payment",
  "features": {
    "amount": 499.99,
    "hour_of_day": 14,
    "is_new_device": false,
    "is_vpn": true,
    "is_emulator": false,
    "is_bot": false,
    "transaction_count_24h": 3,
    "distinct_countries_7d": 1,
    "account_age_days": 120
  }
}
```

**Response `200`:**

```json
{ "score": 32.5, "model_version": "fraud-gbm/v1+onnx" }
```

---

### `POST /v1/models/{name}/activate`

**Request:**

```json
{ "version": 2 }
```

**Response `200`:**

```json
{ "ok": true, "model": "fraud-gbm", "active_version": 2 }
```

---

## Event Ingest — `:8007` {#event-ingest}

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check (includes NATS connection status) |
| `POST` | `/v1/events` | Ingest single event (async via NATS) |
| `POST` | `/v1/events/batch` | Ingest batch of events |
| `WebSocket` | `/v1/events/ws` | Stream events via WebSocket |
| `GET` | `/v1/stream/info` | Get NATS stream metadata |

OpenAPI: _not published under `contracts/openapi/` yet_ (this HTTP table is authoritative).

---

### `POST /v1/events`

**Request:**

```json
{
  "tenant_id": "acme",
  "event_type": "payment",
  "entity_id": "user-42",
  "session_id": "sess-abc",
  "payload": { "amount": 499.99, "currency": "USD" },
  "device_context": null,
  "metadata": {}
}
```

**Response `200`:**

```json
{ "accepted": true, "stream_seq": 1234, "ingest_id": "a1b2c3d4e5f6..." }
```

---

### `POST /v1/events/batch`

**Request:**

```json
{
  "events": [
    { "tenant_id": "acme", "event_type": "login", "entity_id": "user-1", "payload": {} },
    { "tenant_id": "acme", "event_type": "login", "entity_id": "user-2", "payload": {} }
  ]
}
```

**Response `200`:**

```json
{
  "accepted": 2,
  "results": [
    { "ingest_id": "...", "seq": 1235 },
    { "ingest_id": "...", "seq": 1236 }
  ]
}
```

---

### `GET /v1/stream/info`

**Response `200`:**

```json
{
  "stream": "FRAUD_EVENTS",
  "messages": 15234,
  "bytes": 8765432,
  "first_seq": 1,
  "last_seq": 15234,
  "consumer_count": 1
}
```

---

## Feature Service — `:8004` {#feature-service}

Velocity reads and feature snapshots over the same Redis aggregate keyspace as decision-api (when `REDIS_URL` / `FEATURE_SERVICE_REDIS_URL` is set).

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/slo` | In-process HTTP counters and Redis velocity wiring hint |
| `POST` | `/v1/velocity/query` | Multi-window velocity counters for `tenant_id` + `entity_id` |
| `POST` | `/v1/internal/parity/verify` | OSS #48 golden parity: diff live counters vs `expected` within `epsilon` (**200** `ok: true`, **409** drift detail in `detail`) |
| `POST` | `/v1/snapshot` | Canonical feature snapshot for an entity/event |

OpenAPI: `contracts/openapi/feature-service.yaml`

---

## Investigation Agent — `:8006` {#investigation-agent}

Investigation copilot (tools + structured claims) and deterministic evidence surfaces.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/ready` | Readiness |
| `GET` | `/v1/setup` | First-run / integration checklist |
| `GET` | `/v1/integration` | Integration contract snapshot |
| `GET` | `/v1/personas` | Copilot personas |
| `GET` | `/v1/playbooks` | Built-in playbooks |
| `GET` | `/v1/workflows` | SOP workflow manifests |
| `POST` | `/v1/chat` | Chat completion with tools, `claims`, `source_refs`, optional `answer_sections` |
| `POST` | `/v1/chat/stream` | Same as chat over SSE |
| `POST` | `/v1/evidence/summary` | OSS #40 deterministic evidence summary (no LLM): `citations[].resolves_to`, `next_actions`, optional `typology_breakdown` / `decision_audit` / allow-listed `proposed_next_actions` |
| `POST` | `/v1/reports/case-summary` | Case summary PDF from client-supplied fields |
| `POST` | `/v1/reports/turn-bundle` | Turn Markdown + JSON export |
| `POST` | `/v1/feedback` | Turn feedback |
| `GET` | `/v1/feedback/summary` | Feedback aggregates |
| `GET` | `/v1/feedback/recent` | Recent feedback rows |
| `POST` | `/v1/review/turn` | Maker/checker review |
| `GET` | `/v1/review/turn` | Fetch review |
| `GET` | `/v1/review/metrics` | Review metrics |
| `POST` | `/v1/plugin/session` | Plugin session token |
| `POST` | `/v1/plugin/bootstrap` | Plugin bootstrap |

OpenAPI: `contracts/openapi/investigation-agent.yaml`

---

## Collaboration Chat Bridge — `:8009` {#collaboration-chat-bridge}

**Compose default:** host **8009** (`8009:8009` in `deploy/docker-compose.yml`). Do not confuse with the **GraphQL gateway** on **:8010**.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/health` | Health and bridge feature flags |
| `POST` | `/v1/slack/events` | Slack Events API ingress (signature-verified) |
| `POST` | `/v1/teams/messages` | Teams/custom connector message ingress (`X-Bridge-Secret`) |
| `POST` | `/v1/teams/activity` | Bot Framework activity ingress (`X-Bridge-Secret`) |
| `POST` | `/v1/lark/event` | Lark/Feishu event ingress |
| `POST` | `/v1/plugin/session` | Bridge-proxied plugin token issuance (`X-Bridge-Secret`) |
| `POST` | `/v1/plugin/bootstrap` | Bridge-proxied plugin bootstrap (`X-Bridge-Secret`) |

OpenAPI: `contracts/openapi/collaboration-chat-bridge.yaml`

Plugin endpoints include `correlation_id` in the JSON body and `X-Correlation-Id` in response headers for end-to-end traceability.

Ingress audit model:
- `bridge.ingress.audit` is emitted for `slack/events`, `teams/messages`, `teams/activity`, and `lark/event`.
- Slack/Lark async flows emit two events with the same `correlation_id`: an ingress `accepted` event and a completion event that may include `upstream_status`.
- Bridge ingress and plugin endpoints return `X-Correlation-Id` response headers so clients can join request/response traces to audit events.
- Audit payloads include normalized `status_code` and `status_class` (`2xx`/`4xx`/`5xx`) for alerting and low-cardinality dashboards.
- Copy-paste **Grafana / Loki (LogQL)** queries for alerts and Explore: [collaboration chat (ingress + plugin)](guides/investigation-collaboration-chat-aws-azure.md#grafana-loki-logql) and [Enterprise Copilot plugin + governance (bridge audit + labels)](guides/enterprise-copilot-plugin-and-governance-controls.md#grafana-loki-bridge-audit).

---

## GraphQL Gateway — `:8010` {#graphql-gateway}

**Compose default:** host **8010** (`8010:8010` in `deploy/docker-compose.yml`). Do not confuse with the **collaboration chat bridge** on **:8009**.

Strawberry **GraphQL** over HTTP, with the same shared **observability** stack as other Python services (**`GET` `/metrics`**, structured request logging). Send **`X-API-Key`** when the gateway is configured with **`API_KEYS`** (empty keys without `ALLOW_INSECURE_NO_AUTH` yields **`503`** — see `services/graphql-gateway`).

| Kind | Field | Upstream (summary) |
|------|-------|--------------------|
| `Query` | `cases`, `case` | Case API list + get |
| `Query` | `subgraph`, `entity_tags` | Graph Service subgraph + entity tags |
| `Mutation` | `evaluate` | Decision API evaluate (includes `recommended_action` / `inference_context` when the upstream payload provides them) |
| `Mutation` | `create_case` | Case API create |

| Method | Path | Description |
|---|---|---|
| `POST` | `/graphql` | GraphQL queries and mutations |
| `GET` | `/v1/health` | Health (`{"status": "ok"}`) |

OpenAPI: _not published under `contracts/openapi/`._ The schema is **code-first** in `services/graphql-gateway/src/graphql_gateway/schema.py`.

---

## Error Responses {#error-responses}

All services return errors in a consistent format:

**`401 Unauthorized`:**

```json
{ "detail": "invalid or missing API key" }
```

**`404 Not Found`:**

```json
{ "detail": "not found" }
```

**`400 Bad Request`:**

```json
{ "detail": "description of what went wrong" }
```

**`422 Validation Error`:**

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "tenant_id"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**`429 Too Many Requests`:** Returned when rate limit is exceeded.

**`503 Service Unavailable`:** Returned when a required dependency (NATS, Neo4j) is not connected.
