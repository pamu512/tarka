# Feature Flags and Gradual Rollout

Tarka supports tenant-aware gradual rollout through `FEATURE_FLAGS_JSON`.

## Configuration

Set `FEATURE_FLAGS_JSON` to a JSON object keyed by feature name.

Example:

```json
{
  "decision_api_external_signals": {
    "enabled": true,
    "rollout_pct": 30,
    "tenants": ["tenant-enterprise-a", "tenant-canary-b"]
  },
  "decision_api_shadow_eval_async": {
    "enabled": true,
    "rollout_pct": 10
  }
}
```

## Evaluation Rules

1. Missing flag -> default value in code path.
2. `enabled: false` -> always disabled.
3. Tenant in `tenants` list -> always enabled.
4. Otherwise, tenant is enabled if deterministic hash cohort is within `rollout_pct`.

## Current Flags

- `decision_api_external_signals`: enables external signals scoring/enrichment step.
- `decision_api_shadow_eval_async`: enables async shadow evaluation background task.

## Rollout Playbook

1. Start with `rollout_pct: 0` and explicit canary tenant list.
2. Validate telemetry and latency impact.
3. Increase `rollout_pct` incrementally (10 -> 25 -> 50 -> 100).
4. Keep explicit high-priority tenants pinned as needed.
5. Roll back by reducing percentage or disabling feature.

