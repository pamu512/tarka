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
| rule_hit_rate / shadow_divergence | Top-level stays `null`. Pack-scoped values live on `pack_metrics[]` (below). | null |
| join_rate / labeled_receipt_rate | Same in-horizon labeled/receipts ratio. Fuel names M2 effectiveness tick may read later (tick still suggests from `pack_metrics[]`; never auto-demote). | null + `unknown_reasons` |
| labeled_receipt_count / receipt_count | Counts behind the ratio | null |

## pack_metrics[] (`tarka.pack_metrics/v1`)

Additive array on the same `tarka.loop_metrics/v1` payload. Shared by Promote confirm (M3) and Suggest Propose Demote (M2). **null = unknown** — never fake zeros theater. Empty tenant → `pack_metrics: []`. Compute fills a row per tenant pack from Observe logs when `pack_id` is on the observation; otherwise rates stay null.

| Field | Type | Empty / honesty |
|-------|------|-----------------|
| `pack_id` | string | required when a row exists |
| `rule_hit_rate` | number \| null | null = unknown (not 0.0 theater) |
| `shadow_divergence` | number \| null | null = unknown |
| `window` | string | e.g. `7d`; tenant policy, not Tarka morals |
| `as_of` | string \| null | ISO timestamp; null if not computed |

## Join-rate glass

Additive on the same `tarka.loop_metrics/v1` payload. Compute from evaluate receipts + the existing y_label store (G5.1 join keys / `labeled_at_by_trace`) and G5.2 tenant EXAMPLE horizons (`tarka.label_horizon/v1`). **null = unknown** — never fake a 0% bar. Empty tenant / no receipts / no labels / missing store → `null` + `unknown_reasons.join_rate` (`empty_tenant`, `no_receipts`, `no_labels`, `receipt_store_absent`). Buyer owns the lake. Not a CRM. Horizons are tenant policy examples, not Tarka morals. Not a chargeback-guarantee SKU. Low join rate never auto-demotes.

See also [enforcement-v1](enforcement-v1.md), [label-join-v1](label-join-v1.md), and [CLAIM_LOCK](../compliance/CLAIM_LOCK.md).
