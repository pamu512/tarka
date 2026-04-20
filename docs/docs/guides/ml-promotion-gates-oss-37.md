# ML promotion gates (OSS #37)

Versioned policy file: `services/ml-scoring/rules/ml_promotion_policy_v1.json` (copied into the service image next to `models/`).

## Behavior

- **`POST /v1/models/{name}/activate`** and **`POST /v1/models/{name}/traffic-split`** evaluate each **non-heuristic** version that receives traffic against the policy (e.g. `min_training_auc_roc` when &gt; 0, optional `max_training_latency_p99_ms`).
- **Champion vs challenger (golden / offline benchmark)** — optional gates when policy keys are non-null:
  - `max_fp_rate_delta_vs_champion` — requires `training_metrics.benchmark_vs_champion.fp_rate_delta` (challenger minus champion on a fixed dataset).
  - `min_recall_lift_vs_champion` — requires `training_metrics.benchmark_vs_champion.recall_lift`.
  - `max_benchmark_latency_p95_ms` — requires `training_metrics.benchmark_vs_champion.latency_p95_ms`.
- **`GET /v1/models/{name}/{version}/promotion-check`** — dry-run gate with `report` artifact (for CI or release notes) without activating traffic.
- **Rollback** bypasses the gate so operators can recover from bad deploys.
- **`GET /v1/promotion-policy`** — returns the active policy JSON.
- **`POST /v1/admin/promotion-policy/reload`** — reload from disk after edits.

## Policy sources (YAML + JSON)

- Canonical JSON: `services/ml-scoring/rules/ml_promotion_policy_v1.json`
- Human-friendly YAML (must parse identically): `services/ml-scoring/rules/ml_promotion_policy_v1.yaml`
- CI runs `scripts/ml/check_ml_promotion_policy_sync.py` and `scripts/ml/validate_ml_promotion_policy.py --check-sync --strict`.

## Override (break-glass)

- Env **`PROMOTION_GATE_ENFORCE=false`** — disables gate checks (dev only).
- Env **`ML_PROMOTION_OVERRIDE_SECRET`** — when set, HTTP header **`X-Ml-Promotion-Override: <secret>`** skips the gate for that request.

## CI

`scripts/ml/validate_ml_promotion_policy.py --check-sync --strict` validates policy schema, YAML/JSON parity, and shipped model metadata under `services/ml-scoring/models/`.
