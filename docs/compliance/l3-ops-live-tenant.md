# L3 ops live tenant

**Tenant id:** `tarka-ops-live-20260807`  
**Created:** 2026-08-07  
**Purpose:** Named live tenant for the four-week L3 shadow clock (not demo/fixture/sim).

## Honesty

- This id is an **ops-created live tenant label** so the L3 ledger can arm without using banned demo names.
- Arming starts the clock — it does **not** claim L3 COMPLETE.
- COMPLETE still requires four consecutive live weeks of shadow vs host actions, real outcome/label joins, and Week-4 ECE on real labels.
- `scripts/oss/shadow_four_week_sim.py` must never advance the ledger for this tenant.

## Usage

- Evaluate / shadow traffic: `tenant_id=tarka-ops-live-20260807`
- Ledger: `docs/compliance/l3-ops-ledger.json`
- Ops UI: `/ops/shadow`
