# Track: dispute outcomes → calibration y_label auto-merge

**Date:** 2026-08-07  
**Status:** Implemented

## Summary

When a dispute is PATCHed with a terminal outcome (`fraud_confirmed`, `merchant_fault`, `false_positive`, `customer_fault`), case-api maps to binary y_label (`1` / `0`) and fail-soft POSTs to decision-api `POST /v1/calibration/y-labels/merge`. Labels persist in `y_label_store` and join into `GET /v1/calibration/reliability-bins` without manual upload.

## Changes

| Area | File | What |
|------|------|------|
| Mapping | `services/case-api/src/case_api/dispute_y_label.py` | Shared `dispute_outcome_to_y_label` + training-label helper |
| ML reuse | `services/case-api/src/case_api/ml_training_api.py` | Import shared mapping |
| Hook | `services/case-api/src/case_api/dispute_api.py` | `_merge_dispute_y_label` on PATCH outcome (fail-soft) |
| API | `services/decision-api/src/decision_api/calibration_api.py` | `POST /v1/calibration/y-labels/merge` |

## Outcome → y_label

| Outcome | y_label |
|---------|---------|
| `fraud_confirmed`, `merchant_fault` | `1` |
| `false_positive`, `customer_fault` | `0` |
| `inconclusive` / unknown | skip (no merge) |

## Fail-soft

Merge failures log a warning; dispute PATCH still returns 200. Same pattern as `_send_ml_feedback`.

## Config

Uses existing `DECISION_API_URL` + `decision_api_key` on case-api.

## UI (OpsCalibration)

Skipped. Merge endpoint returns per-request `source_breakdown`, but durable store does not retain source metadata — showing dispute-sourced coverage on the desk would require store schema extension. Document-only per “only if cheap” constraint.

## Tests

| Test | Result |
|------|--------|
| `services/case-api/tests/test_dispute_y_label.py` | 4 passed (mapping) |
| `services/case-api/tests/test_dispute_y_label_merge.py` | 2 async passed; TestClient PATCH test requires full case-api deps (CI) |
| `services/decision-api/tests/test_y_labels_merge_endpoint.py` | 1 passed |

Run:

```bash
cd services/case-api && .venv/bin/python -m pytest tests/test_dispute_y_label.py tests/test_dispute_y_label_merge.py -q
cd services/decision-api && PYTHONPATH=src:../shared python3 -m pytest tests/test_y_labels_merge_endpoint.py -q
```

## Constraints honored

- No loyalty re-home
- No forged LIVE pins
- Label merge failure does not fail dispute PATCH
