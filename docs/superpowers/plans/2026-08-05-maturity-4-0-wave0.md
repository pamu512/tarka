# Maturity 4.0 Wave 0–4 Implementation Plan (executed locally)

> Local branch: `maturity-4-0-local` (cloud chat link broken; continue here).  
> Agent workers: waves are gated; Wave 0 honesty closed before brochure UI.

**Goal:** Close honesty + ship golden loop, partner fusion, ops economics, formal rescore.

## Wave 0 (done)

- Stub register + Honesty checklist updated
- CI `scripts/audit_stubs.py` already wired
- README enterprise projections moved to benchmarks README

## Wave 1 (done)

- `label_join.py` + calibration reliability POST + calibration-status `healthy` gate
- Vertical pack `kill_criteria` + simulation `promote_gate`
- `scripts/oss/golden_case_loop_smoke.py`

## Wave 2 (done)

- `partner_fusion.py` + evaluate pipeline wiring
- `docs/docs/guides/partner-enrichment-fusion.md`

## Wave 3 (done)

- `metadata.shadow` non-mutating evaluate
- Case-api QA sample/review/metrics
- Challenge webhook already present; shadow skips it

## Wave 4 (done)

- ML `POST /v1/adaptive/drift/action`
- Customer control evidence pack + export script
- Competitive matrix rescore note (hybrid)

## Verify

```bash
python3 scripts/audit_stubs.py
cd services/decision-api && PYTHONPATH=src pytest tests/test_label_join_and_kill_criteria.py -q
cd services/case-api && PYTHONPATH=src pytest tests/test_qa_sampling.py -q
python3 scripts/oss/golden_case_loop_smoke.py
python3 scripts/compliance/export_control_evidence_index.py
```
