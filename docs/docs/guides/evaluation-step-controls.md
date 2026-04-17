# Decision API: evaluation step controls (#32)

**Purpose:** Bound optional enrichers (lists, feature snapshot, graph risk, ML, OPA) and background graph writes with **timeouts**, **bounded retries**, **fail-open (`SKIP`)** defaults, **Prometheus counters**, and **`step_trace`** on audit `payload_snapshot`.

## Steps instrumented

| Step id | What it wraps | Default timeout (s) | Default max attempts | onFailure |
|---------|----------------|--------------------|----------------------|-----------|
| `list` | Entity list allow/deny/test check | `0.8` | `2` | `SKIP` → treat as no list hit |
| `graph_risk` | Graph service entity-risk GET | `2.5` | `2` | `SKIP` → no graph delta |
| `feature_snapshot` | Feature service snapshot POST | `2.5` | `2` | `SKIP` → local payload snapshot |
| `opa` | OPA fraud bundle POST | `2.5` | `2` | `SKIP` → no OPA deltas |
| `ml_score` | ML scoring POST | `2.5` | `2` | `SKIP` → no ML score |
| `graph_upsert` (background) | Graph entity/link writes | `8.0` | `1` | `SKIP` → log warning |

## Environment variables

All optional; defaults are tenant-safe fail-open.

| Variable | Default |
|----------|---------|
| `EVAL_STEP_LIST_TIMEOUT_SECONDS` | `0.8` |
| `EVAL_STEP_LIST_MAX_ATTEMPTS` | `2` |
| `EVAL_STEP_FEATURE_SNAPSHOT_TIMEOUT_SECONDS` | `2.5` |
| `EVAL_STEP_FEATURE_SNAPSHOT_MAX_ATTEMPTS` | `2` |
| `EVAL_STEP_ML_TIMEOUT_SECONDS` | `2.5` |
| `EVAL_STEP_ML_MAX_ATTEMPTS` | `2` |
| `EVAL_STEP_GRAPH_RISK_TIMEOUT_SECONDS` | `2.5` |
| `EVAL_STEP_GRAPH_RISK_MAX_ATTEMPTS` | `2` |
| `EVAL_STEP_OPA_TIMEOUT_SECONDS` | `2.5` |
| `EVAL_STEP_OPA_MAX_ATTEMPTS` | `2` |
| `EVAL_STEP_GRAPH_UPSERT_TIMEOUT_SECONDS` | `8.0` |
| `EVAL_STEP_GRAPH_UPSERT_MAX_ATTEMPTS` | `1` |

## Metrics (`GET /metrics`)

Counters (in-process, via shared observability):

- `tarka_eval_step_ok_total`
- `tarka_eval_step_timeout_total`
- `tarka_eval_step_http_error_total`
- `tarka_eval_step_error_total`
- `tarka_eval_step_skipped_total`

## Audit

Successful evaluate audits include `payload_snapshot.step_trace`: array of `{step, attempts, status, duration_ms, reason?}`.

## Code

- `services/decision-api/src/decision_api/eval_steps.py` — `run_evaluation_step`
- `services/decision-api/src/decision_api/main.py` — wiring + `_graph_upsert_stepped`
- `services/decision-api/tests/test_eval_steps.py`
