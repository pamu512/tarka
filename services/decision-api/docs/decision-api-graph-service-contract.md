# Decision API ↔ Graph Service contract

This document describes the **runtime contract** between `decision-api` and `graph-service` on the synchronous evaluate path. It reflects the audit of `_fetch_graph_risk_wrapped` → Rule Engine integration (2026-06).

Canonical OpenAPI: [`contracts/openapi/graph-service.yaml`](../../../contracts/openapi/graph-service.yaml).

---

## Scope

| In scope | Out of scope |
|----------|--------------|
| `GET /v1/analytics/entity-risk` during `POST /v1/decisions/evaluate` | `GET /v1/subgraph` (Link Analysis UI) |
| Risk summary **and** named edges / `multi_id_user_ids` / `roles[]` on the receipt | Invented SHARES_*/SAME_AS/RELATED edges |
| Freshness guard in `_fetch_graph_risk` | NATS decision-stream graph indexer (planned) |

---

## Request

Decision API calls graph-service when `GRAPH_SERVICE_URL` is set and the evaluate DAG includes the `graph_risk` step.

```
GET {GRAPH_SERVICE_URL}/v1/analytics/entity-risk
    ?tenant_id={tenant_id}
    &entity_id={entity_id}
    &checkpoint={optional_profile_name}
```

| Query param | Set by | Meaning |
|-------------|--------|---------|
| `tenant_id` | Evaluate body | Tenant isolation key |
| `entity_id` | Evaluate body | Primary **user** id (same public field). Identity in the graph is `(tenant_id, vtype, id)`. |
| `role` | Evaluate body (required) | Registered role string. Unsigned → 422. |
| `checkpoint` | Routing policy or evaluate metadata (`graph_checkpoint`) | **Analytics profile** (`minimal` / `standard` / `deep`), not a timestamp |

Headers: shared upstream auth (`x-api-key` via `_upstream_headers()`).

Timeouts/retries: `EVAL_STEP_GRAPH_RISK_TIMEOUT_SECONDS` (default `2.5`), `EVAL_STEP_GRAPH_RISK_MAX_ATTEMPTS` (default `2`). On failure the step is **skipped** (`on_failure=SKIP`); evaluate continues without graph delta.

Kill switch: tenant flag `disable_graph` in Redis `fraud:tenant_flags:{tenant_id}` → step skipped, tag `graph:disabled_by_tenant`.

---

## Response: `EntityRiskResponse`

JSON is parsed once in `_fetch_graph_risk` via `httpx` `response.json()`. The result is held in local variable **`graph_risk: dict[str, Any] | None`** for the remainder of the evaluate handler.

### Current payload shape

```json
{
  "entity_id": "user-42",
  "risk_score": 58.0,
  "risk_factors": [
    "connected_flagged:2",
    "medium_community:4",
    "shared_devices:1"
  ],
  "connected_flagged_count": 2,
  "community_size": 4,
  "neighbor_device_count": 5,
  "graph_checkpoint": "standard",
  "graph_profile": "standard",
  "graph_profile_multiplier": 1.0,
  "graph_profile_max_neighbor_hops": 3,
  "graph_data_as_of": "2026-06-25T12:34:56.789Z",
  "named_edges": [
    {"from_id": "user-42", "to_id": "dev-1", "type": "USED"}
  ],
  "multi_id_user_ids": ["user-99"],
  "roles": ["member"]
}
```

| Field | Type | Role |
|-------|------|------|
| `entity_id` | string | Echo of queried entity |
| `risk_score` | number 0–100 | Composite heuristic score |
| `risk_factors` | string[] | Human/machine-readable factor codes |
| `connected_flagged_count` | int | Flagged neighbor count |
| `community_size` | int | Bounded neighborhood size |
| `neighbor_device_count` | int | Distinct `device_id` values among 1-hop neighbors |
| `graph_checkpoint` | string \| null | **Profile name** used for this computation (OSS #49) |
| `graph_profile` | string | Resolved profile id from registry |
| `graph_profile_multiplier` | number | Score multiplier from checkpoint registry |
| `graph_profile_max_neighbor_hops` | int | Traversal depth cap (1–5) |
| `graph_data_as_of` | string (ISO-8601 UTC) | **Freshness**: latest graph write time on the entity vertex (`updated_at`, `last_seen`, `tags_updated_at`, or `observed_at`) |
| `named_edges` | object[] | Incident edges with their real type names (never rewritten to RELATED) |
| `multi_id_user_ids` | string[] | Other user vertices that share a bridge |
| `roles` | string[] | `roles[]` on the user vertex |

When the entity is missing from the graph DB, graph-service returns `risk_score: 0`, `risk_factors: ["entity_not_found"]`, and typically **no** `graph_data_as_of`.

### Important: `graph_checkpoint` ≠ freshness

`graph_checkpoint` names an **analytics depth/weight profile** (see `graph-service/rules/checkpoint_profiles_v1.json`). It does **not** indicate when the graph was last indexed.

Use **`graph_data_as_of`** for ingestion lag. Decision API warns when this timestamp is older than `GRAPH_RISK_MAX_AGE_MINUTES` (default **30**, `0` disables).

---

## Graph answers on evaluate (contract v1.2)

Evaluate still keeps `entity_id` as the user id. The hop must also consume **named edges**, `multi_id_user_ids`, and `roles[]` onto `inference_context`, `pack_why.graph`, and the audit receipt. Empty `GRAPH_SERVICE_URL` is `graph:missing` / `graph:unconfigured` — do not stub neighbors. Timeout degrades; do not invent edges.

Rules still match tags and score deltas. Topology is not a second rule language.

### What the Rule Engine actually receives

`graph_risk` is **not** merged into the `features` dict passed to `evaluate_json_rules`. Instead:

| Mechanism | Source | Example |
|-----------|--------|---------|
| `signal_tags` (pre-rules) | `graph_tags_from_risk(graph_risk)` | `graph:high_risk_entity`, `graph:neighbor_device_count_high`, `graph:connected_flagged:2` |
| Score delta (post-rules) | `graph_score_delta(risk_score)` | Up to +20 on base score |
| Rule hit | `graph_delta > 0` | `graph_network_risk` |
| Contextual tags (post-rules) | `derive_contextual_tags(..., graph_risk=...)` | `graph_risk_high`, `network_flagged_neighbors` |
| Audit / inference | `build_inference_context(..., graph_meta=graph_risk)` | `graph_risk_score`, `graph_risk_reasons` |

Raw nodes/edges are **never** passed to the Rust/Python JSON rule engine on this path.

---

## Data freshness guard

Implemented in `_fetch_graph_risk` immediately after JSON parse:

```python
warn_if_graph_risk_stale(
    data,
    max_age_minutes=settings.graph_risk_max_age_minutes,
    tenant_id=tenant_id,
    entity_id=entity_id,
    metrics_inc=_metrics_inc_safe,
)
```

| Signal | When |
|--------|------|
| Log `graph_risk_stale` | `graph_data_as_of` age > `GRAPH_RISK_MAX_AGE_MINUTES` |
| Metric `tarka_graph_risk_stale_total` | Same condition |
| Log `graph_risk_freshness_unparseable` | `graph_data_as_of` present but not ISO-8601 |

The check is **warn-only** — stale graph data still flows to the Rule Engine so operators can detect lag without fail-closing evaluate. Tune the threshold per deployment (batch ingest vs real-time orchestrator writes).

Graph-service sets `graph_data_as_of` from vertex properties; `POST /v1/entities` upserts set `updated_at = datetime()` on Neo4j.

---

## Call stack (evaluate path)

```
evaluate_decision()
  decide_graph_routing()                    # optional skip / checkpoint profile
  run_evaluation_step("graph_risk", …)
    _fetch_graph_risk_wrapped()
      _circuit_graph.call()
        _fetch_graph_risk()                 # GET entity-risk, r.json(), freshness warn
  graph_score_delta / graph_tags_from_risk
  … feature_snapshot → features dict …
  evaluate_json_rules(features, signal_tags)   # tags only, no graph topology
  base_score += graph_delta
  build_inference_context(graph_meta=graph_risk)
```

---

## Related endpoints (not on evaluate path)

| Endpoint | Consumer | Payload |
|----------|----------|---------|
| `GET /v1/subgraph` | Link Analysis UI | `{ nodes[], edges[] }` |
| `GET /v1/entities/{id}/deep-context` | Case / investigation | Neighborhood summary + risk snapshot |
| `POST /v1/entities`, `POST /v1/links` | Ingestion / orchestrator | Writes graph DB |

---

## Versioning

- Inference contract versioning is separate (`inference_schema_version` on governance endpoint).
- Adding **optional** fields to `EntityRiskResponse` is backward compatible.
- Removing or renaming fields requires coordinated releases of graph-service and decision-api.
