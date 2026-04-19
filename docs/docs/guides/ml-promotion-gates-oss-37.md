# ML promotion gates (OSS #37)

Versioned policy file: `services/ml-scoring/rules/ml_promotion_policy_v1.json` (copied into the service image next to `models/`).

## Behavior

- **`POST /v1/models/{name}/activate`** and **`POST /v1/models/{name}/traffic-split`** evaluate each **non-heuristic** version that receives traffic against the policy (e.g. `min_training_auc_roc` when &gt; 0, optional `max_training_latency_p99_ms`).
- **Rollback** bypasses the gate so operators can recover from bad deploys.
- **`GET /v1/promotion-policy`** — returns the active policy JSON.
- **`POST /v1/admin/promotion-policy/reload`** — reload from disk after edits.

## Override (break-glass)

- Env **`PROMOTION_GATE_ENFORCE=false`** — disables gate checks (dev only).
- Env **`ML_PROMOTION_OVERRIDE_SECRET`** — when set, HTTP header **`X-Ml-Promotion-Override: <secret>`** skips the gate for that request.

## CI

`scripts/ml/validate_ml_promotion_policy.py` complements this by checking metadata shape on shipped models.
