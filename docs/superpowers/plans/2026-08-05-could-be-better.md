# Could-be-better Implementation Plan

> **Status:** A–E implemented (2026-08-05)  
> **Spec:** `docs/superpowers/specs/2026-08-05-could-be-better-design.md`

**Goal:** Close end-user “Could be better” residuals without raising hybrid scores above 4.2.

## Tasks

### A — Degraded-mode capability chips

- [x] `capabilityStatus` + vitest helpers (`capabilityDownWarnings`)
- [x] `CapabilityChips` on CaseDetail
- [x] Case-load failure uses `DegradedModeBanner` + retry
- [x] Amber warnings when audit/graph/calibration are **down**

### B — Support / FP kit

- [x] `docs/docs/guides/false-positive-support-kit.md`
- [x] CaseDetail **Copy support-safe summary**
- [x] Link from golden-analyst-loop

### C — Production shadow as product

- [x] `scripts/oss/shadow_vs_primary_diff_recipe.sql`
- [x] `scripts/oss/shadow_promote_gate_smoke.py` (+ CI step)
- [x] `shadow-and-ab-testing.md` named contract rewrite

### D — Bridge Partials

- [x] `.github/workflows/ops-qa-desk-e2e.yml` (weekly + dispatch, Docker Buildx)
- [x] PR template + partner-fusion runbook live/waiver checklist

### E — Honesty lean pass

- [x] `audit_stubs` green
- [x] STUB_REGISTER + Honesty Program refresh

### Narrative

- [x] Regrade canvas + matrix footnote + design spec

## Verify

```bash
python3 scripts/audit_stubs.py
python3 scripts/oss/shadow_promote_gate_smoke.py
cd frontend && npm run test -- --run src/workbench/capabilityStatus.test.ts src/workbench/supportSafeSummary.test.ts
```
