# Inference Track A — chronological ECE gate in CI

Date: 2026-08-06  
Status: approved (approach: CI ECE + committed fixture)  
Program: A → B → A+B claim (Inference ≥4.5 only after A+B)

## Goal

Make closed-loop calibration **durable evidence**: committed chronological labels fixture + PR CI runs `retrain_calibration_ece_gate.py` and requires `gate_passed`.

## Non-goals

- Live tenant labels / 4-week L3 ops claim  
- Loyalty economics (Track B)  
- Claiming Inference **4.5** after A alone (expect ~3.9 Could-be-better)

## Design

1. Fixture `scripts/replay/fixtures/calibration_retrain_labels.json` — schema `tarka.calibration_retrain_labels/v1`, time-ordered rows with score + `y_label`.  
2. CI (`audit-stubs`): run retrain with `--train-fraction 0.7 --ece-threshold 0.05`; assert artifact `gate_passed` and candidate written; upload artifacts.  
3. Existing unit tests remain the fail-path proof.  
4. Honesty: fixture labels ≠ production L3; matrix/canvas note that.
