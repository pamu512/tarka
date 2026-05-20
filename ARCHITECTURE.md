# Tarka V2 — Ingestion sidecar architecture (audit-first)

This document describes the **decoupled sidecar pipeline** under `tarka_v2_core/services/`: **Orchestrator** (ingestion gateway), **Rule Engine** (deterministic AST evaluation), and **Shadow Agent** (optional LLM analyze + persistence). It is distinct from the macroservice **Core API :8000** / **Graph :8001** / **Case :8002** layout in `deploy/docker-compose.lite.yml`.

## Host port convention (V2 local stack)

| Port | Service | HTTP entrypoints | Notes |
|------|---------|------------------|-------|
| **8000** | **Orchestrator** | `POST /v1/ingest` | Single public ingest hop; fans out over HTTP to sidecars. |
| **8001** | **Rule Engine** | `POST /v1/evaluate` | In-process AST ruleset; no LLM. |
| **8002** | **Shadow Agent** | `POST /v1/analyze`, `GET /health`, `GET /health/db` | Optional path; persists `AuditLog` rows. |

**Environment wiring (orchestrator process):**

| Variable | Role |
|----------|------|
| `RULE_ENGINE_URL` | Base URL for rule engine (default in code: `http://127.0.0.1:8778` — override to `http://127.0.0.1:8001` when using the table above). |
| `SHADOW_AGENT_URL` | Base URL for Shadow; empty disables Shadow hop (unless rules never emit `SHADOW_REVIEW`). |
| `SHADOW_API_KEY` | If set, orchestrator sends `X-Shadow-Token` on `POST /v1/analyze`. |
| `ORCHESTRATOR_SHADOW_ANALYZE_TIMEOUT_SECONDS` | Read deadline for Shadow HTTP call (default **3s**); on timeout, ingest still returns **200** with `orchestrator_fallback_decision` / `FLAG` and **no** `shadow_agent` body. |
| `SHADOW_DATABASE_URL` | Async SQLAlchemy URL for Shadow’s DB (audit + case bootstrap). |

Sources: `tarka_v2_core/services/orchestrator/src/orchestrator/main.py`, `rule_engine/main.py`, `shadow_agent/main.py`.

---

## Request / response flow (Mermaid)

### Component flow

```mermaid
flowchart TB
  Client(["Client / load test / Visualizer"])
  O["Orchestrator\n:8000\nPOST /v1/ingest"]
  R["Rule Engine sidecar\n:8001\nPOST /v1/evaluate\nAST ruleset"]
  S["Shadow sidecar\n:8002\nPOST /v1/analyze\nhistory + LLM"]
  DB[("Database\nSHADOW_DATABASE_URL\ncases + audit_logs")]

  Client -->|"Transaction JSON\n(TransactionSchema)"| O
  O -->|"1 same JSON body"| R
  R -->|"actions[], transaction_id"| O
  O -->|"2 only if SHADOW_REVIEW in actions\nsame JSON + X-Shadow-Token"| S
  S -->|"session.add + commit\nAuditLog"| DB
  O -->|"rule_engine + optional shadow_agent\nor FLAG fallback"| Client
```

**Branching rules (implemented):**

1. Orchestrator **always** calls rule engine `POST /v1/evaluate` first with the transaction JSON.
2. If `SHADOW_REVIEW` **∈** `actions` **and** `SHADOW_AGENT_URL` is set, orchestrator calls Shadow `POST /v1/analyze` with the **same** JSON and optional `X-Shadow-Token`.
3. If `SHADOW_REVIEW` **∉** `actions` (e.g. `BLOCK` only), Shadow is **skipped** — no LLM, no audit row from this hop.
4. If Shadow is required but the HTTP call **times out**, orchestrator returns **200** with `orchestrator_fallback_decision: "FLAG"` (no `shadow_agent` key).

### Sequence (happy path + skip path)

```mermaid
sequenceDiagram
  autonumber
  participant C as Client
  participant O as "Orchestrator :8000"
  participant R as "Rule engine :8001"
  participant S as "Shadow agent :8002"
  participant D as Database

  C->>O: POST /v1/ingest (TransactionSchema)
  O->>R: POST /v1/evaluate (same JSON)
  R-->>O: actions, transaction_id

  alt SHADOW_REVIEW in actions
    O->>S: POST /v1/analyze + X-Shadow-Token
    S->>D: read history + commit AuditLog
    S-->>O: ShadowDecision + _debug
    O-->>C: rule_engine + shadow_agent
  else no SHADOW_REVIEW
    O-->>C: rule_engine only
  end
```

---

## Data schema definitions

### 1. Ingest envelope — `TransactionSchema`

Shared Pydantic model (`tarka_v2_core/services/ingestor/src/ingestor/manifest_schema.py`). **Extra fields forbidden.** Used as the **JSON body** for orchestrator `POST /v1/ingest` and forwarded verbatim to rule engine / Shadow.

| Field | Type | Constraints |
|-------|------|-------------|
| `entity_id` | UUID | Primary correlation id; maps to `audit_logs.case_id` after Shadow persists. |
| `amount` | float | `> 0`, finite. |
| `timestamp` | datetime | ISO-8601 on the wire. |
| `metadata` | object | Default `{}`; rule conditions may inspect (e.g. substring `CONTAINS` on serialized metadata in demo rules). |

### 2. Rule engine — `POST /v1/evaluate` response

Produced by `rule_engine/main.py` after `evaluate_ruleset(...)`:

| Field | Type | Description |
|-------|------|-------------|
| `actions` | `string[]` | Wire values from `Action` enum, e.g. `BLOCK`, `SHADOW_REVIEW`, `FLAG`, … |
| `transaction_id` | string | `str(entity_id)` for correlation. |

AST types (`ConditionNode`, `FieldRef`, `Operator`, `Rule`, …) live in `rule_engine/ast_schemas.py`; the demo ruleset is in-memory in `rule_engine/main.py`.

### 3. Shadow — `POST /v1/analyze` response

Validated `ShadowDecision` plus orchestration-only `_debug` (`shadow_agent/main.py`):

**`ShadowDecision`** (`shadow_agent/schemas.py`):

| Field | Type | Constraints |
|-------|------|-------------|
| `transaction_id` | UUID | |
| `risk_score` | float | 0..100 |
| `is_fraud` | bool | |
| `reasoning` | string[] | |
| `confidence_metrics` | object | |

**`_debug`** (response-only, not part of LLM schema):

| Field | Description |
|-------|-------------|
| `audit_log_id` | Surrogate key after commit (or `null` on integrity edge cases). |
| `audit_log_snapshot` | Correlation + capped prompt/response excerpts for operators. |

### 4. Audit trail — SQLAlchemy ORM

`AuditLog` (`tarka_v2_core/services/shared/tarka_shared/audit_trail.py`), table **`audit_logs`**:

| Column | Type | Description |
|--------|------|-------------|
| `id` | int, PK | Autoincrement. |
| `case_id` | string(36), FK → `cases.id` | Set to transaction / entity id for shadow evaluations; `Case` row is ensured before insert. |
| `action_taken` | text | Persisted decision payload / narrative (JSON text in shadow path). |
| `code_executed` | text, nullable | e.g. prompt material / tool trace. |
| `agent_notes` | text, nullable | e.g. model output excerpt. |
| `timestamp` | timestamptz | Server default `now()`. |

Shadow agent loads prior rows for `entity_id` before LLM inference, then **adds + commits** a new `AuditLog` in the same request path (`shadow_agent/agent.py`).

---

## Related paths in repo

| Path | Purpose |
|------|---------|
| `tarka_v2_core/services/orchestrator/` | Ingest gateway, httpx to rule engine + Shadow. |
| `tarka_v2_core/services/rule_engine/` | AST evaluator sidecar. |
| `tarka_v2_core/services/shadow_agent/` | Analyze + audit persistence + Ollama client. |
| `tarka_v2_core/services/ingestor/` | `TransactionSchema` + manifest types. |
| `tarka_v2_core/services/shared/tarka_shared/` | `AuditLog`, `Case`, DB session helpers. |
| `scripts/stress_test_ingestion.py` | Concurrent ingest + optional `audit_logs` count gate. |

---

## Mermaid rendering in the editor

Open this file in the editor and use **Markdown preview** (e.g. “Open Preview” / built-in preview pane). VS Code–compatible Markdown preview renders fenced `mermaid` blocks.
