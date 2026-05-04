# ADR-0004: Feature Flags for Gradual Rollout

- **Status:** Accepted
- **Date:** 2026-04-25

## Context

Platform changes currently rely on global toggles or hard deploy cutovers. This increases risk for high-impact paths where tenant-by-tenant canarying is preferred.

## Decision

Introduce shared, tenant-aware feature flags via `tarka_shared.feature_flags`:

- Config source: `FEATURE_FLAGS_JSON`
- Per-feature controls:
  - `enabled` (bool)
  - `rollout_pct` (0-100)
  - `tenants` (explicit allowlist)
- Deterministic cohort assignment by `(feature, tenant_id)` hash.

Initial production usage:

- `decision_api_external_signals`
- `decision_api_shadow_eval_async`

## Consequences

- Risky capabilities can be canaried per tenant without code forks.
- Rollout behavior is deterministic and auditable.
- Operators can stage adoption and rollback quickly with environment config changes.

