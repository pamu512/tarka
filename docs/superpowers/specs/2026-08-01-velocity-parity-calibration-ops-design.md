# Velocity parity + calibration ops (Waves B / A / C)

**Date:** 2026-08-01  
**Status:** Implemented (Waves B / A / C)

## Goal

Close remaining **operator** gaps on velocity/replay and calibration trust without expanding counter semantics (Epic C freeze).

## Waves

### Wave B — Ops counter UX

- Surface `catalog_version`, `manifest_version`, `redis_key_version` on `OpsCounters`.
- Replace empty `expected: {}` parity call with: live velocity query + optional expected JSON for `/parity/verify`.
- Link to counter replay parity docs.

**Done when:** ops page answers windows / key version / live counters without curling.

### Wave A — Audit-shaped offline parity

- One-command path: audit-shaped rows → replay JSONL → scratch Redis → optional reference diff → JSON report.
- CI/nightly uses audit-shaped fixture (no live Postgres required).
- Reuse `replay_aggregates.py` / `run_offline_parity.py`; no new counter types.

**Done when:** nightly artifact proves audit-shaped events, not only hand-written velocity JSONL.

### Wave C — Calibration trust surface

- Extend `OpsCalibration`: reliability bins fetch + CSV export action; show profile/version/drift already present.
- Short runbook: when to bump calibration profile; proxy-label caveat.

**Done when:** operator can see posture and pull bins/CSV without reading source.

## Out of scope

New velocity windows/keys, consortium, challenge orchestration, full reliability diagram product.
