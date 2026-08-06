# Inference Track A — ECE CI Implementation Plan

> **For agentic workers:** implement tasks below; verify each. Do not claim Inference 4.5. Do not commit unless user asks.

**Goal:** PR CI proves chronological Platt retrain with held-out ECE gate on a committed fixture.

**Files:**
- Create: `scripts/replay/fixtures/calibration_retrain_labels.json`
- Modify: `.github/workflows/ci.yml` (audit-stubs step)
- Optional: extend `test_retrain_calibration_ece_gate.py` to load committed fixture
- Modify: regrade canvas + matrix (Inference ~3.9 after A)

## Task 1: Fixture

Generate ≥80 chronological rows (well-calibrated scores vs labels). Schema:
`{"schema_id":"tarka.calibration_retrain_labels/v1","rows":[...]}`

Verify: `python3 scripts/oss/retrain_calibration_ece_gate.py --labels <fixture> --out /tmp/c.json --artifact-out /tmp/a.json --train-fraction 0.7` exits 0 and `gate_passed`.

## Task 2: CI

Add step after partner/counter gates on `audit-stubs`: pip not needed if stdlib+decision-api path; PYTHONPATH includes decision-api src. Fail unless `gate_passed`. Upload artifacts.

## Task 3: Partial regrade

Inference → ~3.9 Could-be-better; ECE “unused” closed; no product-wide 4.2 / Inference 4.5.
