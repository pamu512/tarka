# Enterprise parity (competitor-aligned capabilities)

This guide documents **shipping surfaces** that align Tarka with enterprise fraud platforms (schemaless ingest, bulk historical load, analyst-facing rule tooling, vendor plugins, embedded KPIs, and SAR filing hardening). It complements the internal architecture plan (not duplicated here).

**Environment quick reference:** [competitor-parity-env.md](../../architecture/competitor-parity-env.md)

## Event ingest — schemaless path

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/ingest/dynamic` | Accept flexible JSON; map via **in-memory + optional Redis** cache or **heuristics**; publish `fraud.ingest.mapping.request` when no map exists (PII-tokenized sample only). |
| `POST /v1/internal/ingest/mapping-cache` | Persist a mapping for `tenant_id` + `schema_fingerprint` (operator or mapping worker). |

**Streams:** JetStream **`FRAUD_INGEST_MISC`** carries `fraud.ingest.dlq` and `fraud.ingest.mapping.request`.

**Compliance:** When `INGEST_PII_TOKENIZE` is enabled, samples used for async mapping proposals are tokenized before leaving the service.

**Code:** `services/event-ingest/src/dynamic_ingest.rs`, `services/event-ingest/src/main.rs`.

## Historical backfill (offline)

**`batch-ingest`** is a standalone Rust binary: CSV → ClickHouse `fraud_features_offline` with **line checkpoints**. It does **not** connect to NATS or `fraud.decisions.>`.

- **Run:** `scripts/run-batch-ingest.sh -- --csv ./data/history.csv --clickhouse-url http://localhost:8123`
- **Docs:** `services/batch-ingest/README.md`

## Decision API — rules studio, backtest, reporting, feature store, dashboards, vendors

| Prefix | Role |
|--------|------|
| `/v1/rules/visual/compile` | Compile a **visual AST** JSON payload into a deployable JSON rule pack. |
| `/v1/rules/gitops/approve` | Persist **maker/checker** approval rows (`rule_approvals`) and return `audit_token`. |
| `/v1/rules/backtest/preview-sql` | Return **ClickHouse SQL** for a 90-day window with **PIT** guidance in the payload. |
| `/v1/rules/backtest/jobs` | Enqueue streaming OLAP backtest (ClickHouse/DuckDB → Rust → Postgres); poll `GET .../jobs/{id}`. |
| `/v1/rules/backtest/run` | **410 Gone** — former stub route removed; use `/jobs`. |
| `/v1/reporting/nl-to-sql` | NL → bounded SQL (LLM when configured; template fallback otherwise). |
| `/v1/feature-store/definitions` | Durable Postgres definitions + ClickHouse MV DDL execution. |
| `/v1/analytics/dashboards/kpis` | Live KPI counts from analytics engine; **503** when offline (no null stub dashboards). |
| `/v1/calibration/reliability-export.csv` | Audit-score CSV for offline reliability curves (Wave 1 trust). |
| `/v1/vendors/registry`, `/v1/vendors/probe` | Vendor **plugin registry** + admin probe. |

**Code:** `services/decision-api/src/decision_api/rule_compiler_api.py`, `rule_gitops_api.py`, `backtest_api.py`, `reporting_nl.py`, `feature_store_api.py`, `analytics_dashboards.py`, `vendor_marketplace_api.py`, `vendors/`.

## ML scoring — model reload webhook

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/models/reload` | Rescan ONNX registry + reload `ONNX_MODEL_PATH` session; optional header **`x-ml-webhook-secret`** when **`ML_MODEL_WEBHOOK_SECRET`** is set. |

**Code:** `services/ml-scoring/src/ml_scoring/main.py`.

## Case API — queue routing & SAR

- **`CASE_QUEUE_ROUTING_RULES_JSON`:** JSON array of `{ "when": { "priority": "critical" }, "assigned_team": "Tier3" }` rules evaluated on **`POST /v1/cases`** to set `assigned_team`.
- **SAR:** `POST /v1/cases/{id}/sar/generate` returns **`prefiling_validation_errors`** for FinCEN XML; when **`FINCEN_BSA_SFTP_HOST`** is set, an ACK poll hook is scheduled (implement worker for production).

**Code:** `services/case-api/src/case_api/routing.py`, `sar_filing_transport.py`, `main.py`.

## Frontend — analyst & executive surfaces

| Route | Purpose |
|-------|---------|
| `/rules/visual` | Visual rule builder → calls Decision API compile. |
| `/exec-dashboards` | Embedded KPI view (Recharts) → calls `/v1/analytics/dashboards/kpis`. |
| `/graph` | Graph Explorer (vis-network) includes **super-node** operational guidance. |

## Graph service — real-time edge projection

Design for indexing **`fraud.decisions.>`** into the graph store without starving interactive Gremlin workers:

- **`services/graph-service/docs/DECISION_STREAM_INDEXER.md`**

## First-party device SDK

- **`@tarka/sdk`** (`packages/fraud-sdk-typescript`) — browser DecisionClient + consent-gated CNAME helpers (merged former `tarka-web-sdk`).

## Related

- Tier-1 resilience plan (branch `1.2.0`): [v1.2.0-tier-1-promises-plan.md](../../architecture/v1.2.0-tier-1-promises-plan.md)
