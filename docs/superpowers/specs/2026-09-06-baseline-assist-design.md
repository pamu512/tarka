# Baseline assist on registry names (P-reg2)

**Date:** 2026-09-06  
**Status:** Implemented on `honesty/baseline-assists`.  
**Branch:** `honesty/baseline-assists` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** [field registry + onboarding map](./2026-09-05-field-registry-map-design.md), `services/shared/author_catalog.py`, `services/shared/fraud_aggregates.py`, `docs/docs/guides/velocity-atoms.md`

## Goal

One Python-computed baseline assist on existing Redis velocity keys. Packs FLAG on deviation from a pack-configured threshold. Windows stay on `counter_manifest`. Missing history stays missing (key absent), not zero-safe.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off.
- **No** `rate` / `baseline_ratio` Redis keys. **No** new Rust `velocity_v1`. **No** `velocity()` in pack JSON.
- **No** new `counter_manifest` kind. **No** windows / baselines / hop etypes in the registry.
- **No** `desk_provision.json` (P-day1). Warmup is env until then.
- One assist only: `event_count_1h_share_24h`.
- Demo ≠ product. Do not change `make demo`, default-live demo packs, or clone-demo.
- No named third-party desks in published copy. Do not call Tarka OSS in new docs. Keep `scripts/oss/` path names.

## Why this formula

Redis already exposes `event_count_1h` and `event_count_24h`. A short/long share is the classic “this hour vs the day” spike. `AggregateStore.count` returns `0` for an empty window, and some matchers coerce a missing field to `0.0`. Writing a ratio of `0/0` or treating first-event `1/1` as a FLAG would lie. The assist is therefore **omitted** until 24h history meets a warmup.

Rejected: `amount / avg_amount_24h` (amount outlier, not velocity). Rejected: env ceiling on `event_count_1h` only (not a computed assist). Rejected: new manifest ratio kind (looks like Redis; easy to write `0`). Rejected: Rust atom (locked out).

## Units

### 1. Assist formula

Name: `event_count_1h_share_24h`.

```
if event_count_24h >= warmup:
    value = clamp(event_count_1h / event_count_24h, 0, 1)
else:
    omit the key
```

- Inputs are the Redis features already on the evaluate dict after `compute_features`.
- Compute **after** `features.update(agg_features)` and **before** `record_event`. This event is not in the 1h/24h counts yet.
- `warmup` = `TARKA_BASELINE_WARMUP_24H`, integer, default **10**. Invalid / missing env → default 10. Values `< 1` → treat as 1 (still refuses `0/0`).
- If `event_count_24h` is missing or not a number → omit.
- If `event_count_1h` is missing, treat as `0` **only when** 24h already passed warmup (hour really empty).
- `0.0` is a real value only after warmup (no events this hour, enough in 24h).
- Never write the key as `0` to mean “no history.” Never write `rate` or `baseline_ratio`.
- Do not persist the share in Redis.

FLAG threshold is the pack `when.value` (normal `gte` / `gt`). Not an env.

### 2. Helper

One function in `services/shared/baseline_assist.py` (not in `fraud_aggregates`, not a Redis kind):

`apply_count_share(features: dict, warmup: int) -> None`

Mutates `features` in place: sets or deletes `event_count_1h_share_24h`. Idempotent. Decision-api evaluate pipeline is the only production caller. Tests call the helper directly.

Constants on that module: `COMPUTED_NAME = "event_count_1h_share_24h"`, `DEFAULT_WARMUP_24H = 10`.

### 3. Catalog

`GET /v1/rules/author-catalog` gains:

```
"computed": [
  {
    "name": "event_count_1h_share_24h",
    "explanation": "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin"
  }
]
```

Always one row. Not gated on graph URL. Not a registry row. Not a `/v1/fields` name.

- `catalog_field_names` includes `computed[].name`.
- `ai_allowed_fields` therefore includes it. Still excludes `rate` / `baseline_ratio`.
- Desk `/rules` picker: new **Computed** group (form + visual Feature picker).
- Frontend `AuthorCatalog` type, `catalogFieldNames`, `rulesPickerGroups`, `featurePickerGroups`, and `fallbackAuthorCatalog` include `computed`.
- Leftover visual `parseVelocityField` stays redis ∪ growth only. This name is not a velocity atom.

### 4. Reserved name

`event_count_1h_share_24h` cannot become a registry overlay, a map target, or a seed row.

- `validate_registry_name` rejects it (same path as `LEGACY_ALIASES`).
- Overlay PUT and `PUT /v1/fields/maps` with `registry_name` equal to it → 400.
- Do not add it to `field_registry_v1.json`.

### 5. Docs + example

- Update `docs/docs/guides/velocity-atoms.md`: one computed row. State it is **not** a Redis key. Point at Observe calibration: `score_delta` on this assist is not a calibrated score (P-obs1). Do not invent a second baseline guide.
- One example pack JSON under `docs/docs/guides/examples/` that FLAGs `when.field=event_count_1h_share_24h` `gte` a threshold. **Not** default-live. Demo packs unchanged.

### 6. Config

| Name | Default | Role |
|------|---------|------|
| `TARKA_BASELINE_WARMUP_24H` | `10` | Minimum `event_count_24h` before the assist is attached |

No other env. No `desk_provision.json`.

## Data flow

1. Evaluate remaps buyer keys (P-reg1).
2. Redis `compute_features` writes `event_count_1h` / `event_count_24h` (and the rest).
3. `apply_count_share(features, warmup)`.
4. Pack `when` runs on the feature dict. Existing `_match_condition` / Rust parity: numeric `gte`/`gt`/`lte`/`lt` are false when the field is absent (`None` is not coerced to `0`). Authors use `gte`/`gt` for FLAG. Do not change the Rust engine. Do not coerce this key to `0` in the helper.
5. `record_event` as today.

Demo evaluate with empty Redis: 24h count is `0` → key omitted → existing demo packs that do not mention the name behave as today.

## Error handling

- Redis / aggregate failure: existing degrade path. Helper sees missing counts → omits.
- Warmup env garbage: default 10, log once.
- Helper never raises on bad feature types.

## Testing

- Helper: 24h `<` warmup → key absent; 24h `>=` warmup → value equals `1h/24h`; 24h `0` → absent; 1h `0` and 24h warmup-met → `0.0`; existing keys other than the assist unchanged.
- Catalog GET includes the computed row; `ai_allowed_fields` includes the name; `rate` / `baseline_ratio` still absent.
- Overlay PUT / map to the reserved name → 400.
- Evaluate fixture: thin history omits the key on the feature map / receipt; warmed history includes the float.
- Author catalog frontend types / fallback still parse (Computed group present).
- Existing aggregate tests, evaluate fixtures, and `walk_receipts` honesty: no default-live pack change, so demo walk stays the same.

## Success

Documented deviate-from-baseline → FLAG path: author catalog shows `event_count_1h_share_24h`, a pack `when` on that name FLAGs only after warmup, thin history cannot look like a safe zero. Demo still works.

## Non-goals

- Z-score, amount/avg ratio, extra computed names.
- `rate` / `baseline_ratio` Redis keys or catalog fields.
- New Rust atom. New manifest kind. Windows in the registry.
- `desk_provision.json`. Observe calibration window (P-obs1).
- Changing Redis `count()` to return `None` (out of scope; warmup is the honesty gate).
- Live demo pack / `make demo` / clone-demo / Hunt copy.
- P-ing1, P-graph1, P-left1, P-enf1.

## Done when

On a branch stacked on `#378`: evaluate attaches `event_count_1h_share_24h` only after 24h warmup; catalog GET lists it under `computed`; packs can author a FLAG on it; overlay/map cannot steal the name; velocity-atoms names the assist and points at calibration; demo default-live packs and `walk_receipts` stay unchanged.
