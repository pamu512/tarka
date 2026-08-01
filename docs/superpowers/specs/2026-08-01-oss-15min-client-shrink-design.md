# OSS 15-minute path + client/mockData shrink (A+B)

**Date:** 2026-08-01  
**Status:** Implemented

## A — 15-minute path

- Guide: `docs/docs/guides/oss-15-minute-first-decision.md`
- Smoke: `scripts/oss/first_decision_smoke.py`
- Community env: `ALLOW_INSECURE_NO_AUTH=true` for local try-it
- README deep link

## B — Shrink

- `frontend/src/api/mockData.cases.ts` (health + evidence-bundle)
- `frontend/src/api/v1/cases.ts`
- `CaseDetail` imports versioned cases client
