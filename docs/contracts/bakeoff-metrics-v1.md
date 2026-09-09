# Bake-off metrics v1

Numbers for Observe/shadow of a pack. Thresholds are **tenant policy**, not Tarka morals. Empty tenant → zeros / nulls.

`GET /v1/observe/loop-metrics?tenant_id=` and alias `GET /v1/ops/bakeoff` return `schema_id: tarka.loop_metrics/v1` plus additive fields. No schema-id bump: GLOBAL keys stay on this payload.

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
| evaluate_count / action_mix | Top-level GLOBAL (below). Filled from audit/receipts when the store is present. | null |
| rule_hit_rate / shadow_divergence | Top-level `rule_hit_rate` stays `null` (M3 per-pack only). Top-level `shadow_divergence` is GLOBAL (below); pack-scoped values live on `pack_metrics[]`. | null |
| join_rate / labeled_receipt_rate | Same in-horizon labeled/receipts ratio. Fuel names M2 effectiveness tick may read later (tick still suggests from `pack_metrics[]`; never auto-demote). | null + `unknown_reasons` |
| labeled_receipt_count / receipt_count | Counts behind the ratio | null |

## Tip inventory (D8.1)

Same `tarka.loop_metrics/v1` object. Do not invent extra metrics.

| Scope | Fields | Tip status |
|-------|--------|------------|
| W1 loop | `leftover_*`, `drafts_to_observe`, `ai_backtest_block_rate`, `fp_*`, `label_latency_*`, `promote_ttl_*`, `demote_*_count` | filled |
| M3 pack | `pack_metrics[]` (`rule_hit_rate`, `shadow_divergence`, `window`, `as_of`) | filled from Observe logs when `pack_id` is on the row |
| D8 GLOBAL | top-level `evaluate_count`, `action_mix`, `shadow_divergence` | filled from audit/receipts/shadow pairs when present; **null = unknown** |
| unused top-level | `rule_hit_rate` | stays `null`; M3 owns the per-pack name only |

## GLOBAL fields (D8 — tenant-level)

LoopScoreboard / bakeoff fill. Not Promote-card pack bind. Window default matches `pack_metrics[]`: `7d` (tenant policy, not Tarka morals). `as_of` optional ISO when D8.2 computes.

| Field | Type | Definition | Honesty |
|-------|------|------------|---------|
| `evaluate_count` | number \| null | Count of evaluate receipts / audit rows for the tenant in the window. Source: audit / evaluate receipts (D8.2). | **null = unknown** (store absent or not computed). Do not emit `0` when the store is missing. `0` is only valid after compute scanned and found none. |
| `action_mix` | object \| null | Histogram of evaluate HTTP `action` tokens from [enforcement-v1](enforcement-v1.md) (`allow` / `review` / `deny` / `flag` / …). Keys are observed actions only. | **null = unknown**. Do not emit `{allow: 0, deny: 0, …}` theater or a fake 0% bar. Empty `{}` is not a substitute for unknown. |
| `shadow_divergence` | number \| null | Observe/shadow vs Active pack decision delta at the tenant window. Same name and type as `pack_metrics[].shadow_divergence`. | **null = unknown**, not `0.0` theater. `0.0` only if compute found paired decisions and none diverged. |

Never invent a new metric name. Evaluate stays Rust; this contract only names aggregates.

### reason_code (optional companion)

When a GLOBAL field is null, D8.2 MAY set `reason_code` (string) or a small `unknown_reasons` map (`evaluate_count` / `action_mix` / `shadow_divergence` → code). Examples: `evaluate_store_absent`, `no_shadow_live_pairs`, `empty_tenant`, `not_computed`. LoopScoreboard shows `—` plus short English for that reason (e.g. no audit in window / metrics not yet available). Missing `reason_code` still means unknown, not 0%.

## M3 vs D8 ownership (share-with-M3 / do-not-double-implement)

- **M3 owns** `pack_metrics[]` (`tarka.pack_metrics/v1`) for Promote confirm (and M2 Suggest Propose Demote). Per-pack `rule_hit_rate` / `shadow_divergence`.
- **D8 owns** tenant-level aggregates `evaluate_count`, `action_mix`, and top-level `shadow_divergence` for LoopScoreboard / `/ops/bakeoff`.
- Share naming and types with M3. Do not fork a second pack_metrics schema. Do not duplicate compute modules — D8.2 reuses M3 helpers for `shadow_divergence` math when it lands.
- Top-level `rule_hit_rate` stays null. D8 does not invent a tenant-level hit-rate.

## Coexistence (D8 globals + M3 pack_metrics[])

Same `tarka.loop_metrics/v1` object. Two scopes, two desks — they do not overwrite each other.

| Surface | Reads | Honesty |
|---------|-------|---------|
| LoopScoreboard / `/ops/bakeoff` | top-level GLOBAL `evaluate_count` / `action_mix` / `shadow_divergence` | **null = unknown**, never fake 0% |
| Promote confirm (M3) / Suggest Propose Demote (M2) | `pack_metrics[]` row for that pack, or honest empty | null rates = unknown |

Filling GLOBAL keys must not drop, zero, or rewrite `pack_metrics[]`. Filling a pack row must not drop or fake-zero GLOBAL keys. Do not mint `tarka.loop_metrics/v2`. Do not fork `tarka.pack_metrics/v1`. Thresholds are tenant policy, not Tarka morals.

## null vs 0 honesty

Prefer **null + reason_code** over fake 0%. `null` = unknown. `0` / `0.0` = measured none (only after D8.2 scans a real store). Empty tenant without a store → nulls, not demo zeros. No CRM analytics product.

## Schema additive note

`schema_id` stays `tarka.loop_metrics/v1`. Additive keys only. Do not mint `tarka.loop_metrics/v2` or a forked global pack-metrics id.

## LoopScoreboard bind (D8.3)

LoopScoreboard reads top-level GLOBAL fields only. Non-null → counts / rate. Null → em-dash `—` plus short English from `unknown_reasons[field]` or `reason_code`. Never fake 0%. Parent-fed: OpsShadow refetches on tenant change and clears first. Does not bind `pack_metrics[]` (M3 Promote confirm).

## Out of scope (this slice)

Re-implementing M3 Promote confirm pack bind. Auto-demote / auto-Promote. CRM analytics. Invented metrics. Analytics maturity matrix.

See also [enforcement-v1](enforcement-v1.md) and [CLAIM_LOCK](../compliance/CLAIM_LOCK.md).

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
