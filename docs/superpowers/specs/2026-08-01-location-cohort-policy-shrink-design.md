# Location, cohort, policy-check, client shrink (Waves A–D)

**Date:** 2026-08-01  
**Status:** Approved (user: go)

## Waves

### A — Location / co-presence (productize)

- Demo: `scripts/oss/copresence_demo.py` → location-service `/v1/evaluate` with multi-session features
- Rule pack example (shadow): `services/decision-api/rules/location_copresence_v1.json`
- Contract test: `test_location_copresence_rules.py` (inference meta → rule hits)
- Doc: `docs/docs/guides/location-context-and-trusted-places.md`

### B — Cohort / benchmark

- Doc + permissions: `docs/docs/guides/cohort-compare-ops.md`
- Cases queue: cohort panel with recent/prior counts + % KPI (existing API)

### C — Policy-as-code CI

- `make policy-check` → `validate_rule_packs.py` + `validate_opa_bundle.py`
- `audit-stubs` uses `make policy-check`
- Focused workflow: `.github/workflows/policy-check.yml`

### D — mockData / client shrink

- `mockData.disputes.ts` + `api/v1/disputes.ts`
- Disputes list/detail import versioned client

## Out of scope

New location microservice, Incognia-class device network, required-branch OPA-only gate beyond existing validators, full mockData rewrite.
