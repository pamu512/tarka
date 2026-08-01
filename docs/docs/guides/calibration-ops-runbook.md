# Calibration ops runbook

**Audience:** fraud ops / platform engineers  
**UI:** `/ops/calibration` · APIs under `/v1/ops/calibration-status` and `/v1/calibration/*`

## When to bump a calibration profile

Bump (or cut over) the tenant calibration **profile** when any of these hold:

1. **Drift hint elevated** — `GET /v1/ops/calibration-status` (or Drift hint on the ops page) shows a non-`ok` hint / rising `drift_score` after a rule-pack or model change.
2. **Rule pack / typology cutover** — active pack SHA or typology version changed and score distributions shifted (confirm via calibration snapshots).
3. **Integrity schema change** — `inference_schema_version` moved and confidence tiers are no longer comparable to the pinned reference.

Pin a new reference with `POST /v1/calibration/reference/{profile}` after the cutover window is stable. Keep the old profile name available until holdout review finishes.

## Reliability bins / CSV caveat

- `GET /v1/calibration/reliability-bins` and `…/reliability-export.csv` use `decision_audit` scores.
- When case disposition labels (`y_label`) are absent, bins use **`proxy_label_from_decision`** (block/review-like → 1, allow-like → 0). That is **not** ground truth.
- For true reliability diagrams, join dispute/case outcomes into `y_label` offline (warehouse or notebook), then re-bin.

## Quick checks

```bash
# Posture + drift
curl -sS "$DECISION_API/v1/ops/calibration-status?tenant_id=$TID&profile=default" | jq .

# Bins (analyst role)
curl -sS "$DECISION_API/v1/calibration/reliability-bins?tenant_id=$TID&n_bins=10" | jq .
```

Related: [counter-replay-parity.md](./counter-replay-parity.md), aspirational Phase 1 in [aspirational-gaps-execution-plan.md](./aspirational-gaps-execution-plan.md).
