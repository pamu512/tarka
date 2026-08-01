# Decide → act enforcement (Waves A–C)

**Date:** 2026-08-01  
**Status:** Approved (user: go, approach C)

## Goal

Make platform protect loop provable: sync `enforcement_action` on evaluate + existing signed webhooks + mock receiver/demo.

## Waves

### A — Sync `enforcement_action`

Reuse `resolve_enforcement_action` → `allow` | `step_up` | `block` on `EvaluateResponse` and audit/decision-log snapshot.

### B — Mock receiver + demo

Stdlib mock webhook + smoke script; align challenge step-up aliases with enforcement.

### C — Ops + docs

Posture/governance flag for enforcement webhook; decide→act guide; hardening env comments.

## Out of scope

SMS/WebAuthn providers, new orchestration microservice, case-create changes.
