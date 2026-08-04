# Thin-fix Waves 1–3

**Date:** 2026-08-04  
**Status:** Implemented (branch `feat/ops-golden-holdout`; Waves 1–3)

## Wave 1
- SDK + golden: `enforcement_action` on TS (and Python if typed) EvaluateResponse; contract-check aware
- Cohort: decision mix / score summary on `cohort-compare` + Cases UI

## Wave 2
- SR-10: deeper `validate_pre_filing` (required keys + XML non-empty when fincen_xml)
- Integrity: gate step_up/block recommendations when below platform min_integrity_confidence (unless deny)

## Wave 3
- Enforcement delivery journal: append webhook attempt records (path under rules/data); ops/governance flag + list endpoint or log file

## Out of scope here
SR-15/16/17, sanctions rewrite, challenge providers, Waves 4–6.
