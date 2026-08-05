# Maturity Wave 5 Implementation Plan (executed locally)

> Branch: `maturity-4-0-local`. Verify suite green 2026-08-05.  
> **For agentic workers:** Implement 5a then 5b. TDD for new logic. Verify with commands at bottom.

**Goal:** Evidence gates + smallest ops slice toward honest 4.0–4.2.

**Spec:** `docs/superpowers/specs/2026-08-05-maturity-wave5-design.md`

## File map

| File | Role |
|------|------|
| `docs/docs/guides/competitive-score-matrix-2026-04.md` | Honest hybrid column |
| `docs/docs/guides/competitive-module-rescore-post-parity-2026-04.md` | Pull back overclaimed module means |
| `scripts/oss/partner_fusion_fixture_smoke.py` | Fusion fixture smoke |
| `scripts/oss/golden_case_loop_smoke.py` | `REQUIRE_DECISION_API` |
| `scripts/oss/counter_replay_job.py` | Job wrapper + artifact |
| `scripts/oss/qa_desk_smoke.py` | QA helper + API contract smoke |
| `scripts/audit_prod_desk_mocks.py` | Prod mock forbid gate |
| `.github/workflows/ci.yml` | Wire maturity smokes |
| `services/decision-api/tests/test_partner_fusion_fixture.py` | TDD fusion fixture |

## Tasks

### Task 1: Honest matrix
Rewrite hybrid scores to regrade (~3.2 six-cap mean); mark 4.0–4.2 as target.

### Task 2: Fusion fixture smoke (TDD)
Fixture signals → `signals_to_feature_tags` + `graph_writeback_hints`; script + pytest.

### Task 3: Golden harden
`REQUIRE_DECISION_API=1` → exit 1 if URL unset; keep offline default.

### Task 4: Counter replay job
Wrap dual fixture replay or fixture-validate dry-run; write `artifacts/counter-replay-job.json`.

### Task 5: Prod desk mock gate
Static check: production forbids `VITE_USE_API_MOCKS=true`; client guard present.

### Task 6: QA desk smoke
Offline: sample + disagreement_metrics; document ops routes.

### Task 7: CI wire
Add maturity smoke steps to `ci.yml` (no Redis required for default path).

## Verify

```bash
python3 scripts/audit_stubs.py
python3 scripts/audit_prod_desk_mocks.py
python3 scripts/oss/partner_fusion_fixture_smoke.py
python3 scripts/oss/golden_case_loop_smoke.py
python3 scripts/oss/qa_desk_smoke.py
python3 scripts/oss/counter_replay_job.py --dry-run
cd services/decision-api && PYTHONPATH=src pytest tests/test_label_join_and_kill_criteria.py tests/test_partner_fusion_fixture.py -q
cd services/case-api && PYTHONPATH=src pytest tests/test_qa_sampling.py -q
```
