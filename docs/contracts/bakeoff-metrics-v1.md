# Bake-off metrics v1

Numbers for Observe/shadow of a pack. Thresholds are **tenant policy**, not Tarka morals. Empty tenant → zeros / nulls.

`GET /v1/observe/loop-metrics?tenant_id=` and alias `GET /v1/ops/bakeoff` return `schema_id: tarka.loop_metrics/v1` plus additive fields.

| Metric | Tip field | Empty |
|--------|-----------|-------|
| leftover→draft p50/p95 | `leftover_to_draft_ms` | null |
| leftover mint rate | `leftover_mint_rate` (leftover drafts / Observe drafts) | null |
| drafts to Observe | `drafts_to_observe.{human,ai}` | 0 |
| AI backtest block rate | `ai_backtest_block_rate` | null |
| FP count / cost | `fp_count`, `fp_cost_sum` | 0 |
| label latency | `label_latency_ms` + `label_latency_hours` | null |
| promote TTL | `promote_ttl_ms` + `promote_ttl_hours` | null |
| demote propose/confirm | `demote_propose_count`, `demote_confirm_count` | 0 |
| evaluate_count / action_mix | `null` (forward — evaluate store not on this payload) | null |
| rule_hit_rate / shadow_divergence | `null` (forward — pack-scoped Observe divergence not on this payload) | null |

See also [enforcement-v1](enforcement-v1.md) and [CLAIM_LOCK](../compliance/CLAIM_LOCK.md).
