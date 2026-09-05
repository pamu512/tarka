# Field registry + onboarding map (P-reg1)

**Date:** 2026-09-05  
**Status:** Design — approved in chat; not implemented.  
**Branch:** `honesty/field-registry-v1` from `#377` / `feat/desk-demo-vs-product`  
**Related:** [leftover Hunt visual Observe](./2026-09-05-leftover-hunt-visual-observe-design.md), `services/shared/author_catalog.py`, `services/decision-api/src/decision_api/data/counter_manifest_v1.json`

## Goal

A feature exists because onboarding **mapped** a buyer key onto a **Tarka field name** (plus explanation). The author catalog is no longer “whatever the manifest lists.” It is:

**registry names ⋈ `counter_manifest` windows ⋈ hops/growth as `#377` already ships.**

Unmapped payload keys surface as `new_feature` candidates. Packs cannot author a `when.field` that is not on the live allow-list. Evaluate remaps buyer keys to registry names before Redis compute. Windows, baselines, and hop etypes stay out of this table.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off. Graph keys **absent** when the graph URL is empty (do not write `0`).
- No `rate` / `baseline_ratio`. No new Rust `velocity_v1`. No `velocity()` in pack JSON.
- No windows, baselines, or hop etypes **in the registry**. `window_seconds` stays on `counter_manifest_v1.json`. Growth stays `GRAPH_GROWTH_WINDOWS` + graph policy GET. Hops stay `CATALOG_HOPS` (`USES_DEVICE`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_CARD`, `HAS_LIST`).
- One naming going forward. New registry names must match `^[a-z][a-z0-9_]{0,127}$` and must **not** start with `tx_`. Legacy aliases (`tx_count_*`, `tx_amount_*`, `distinct_devices_24h`, `distinct_ips_24h`) stay **read-only** on the AI/human allow-list. Do not insert them as new registry rows.
- Do not reuse `feature_definitions` (ClickHouse DDL metadata). New tables.
- Do not add `desk_provision.json` (later Day-1 slice).
- Do not open the `EventType` 5+`custom` enum (later ingest slice).
- Do not change SDK always-false / missing semantics (later ingest slice).
- Do not attach a `registry_id` onto evaluate feature maps. Remap **names**; evaluate JSON shape stays today’s feature dict.
- Do not add Feast or a feature-store product.
- No named third-party desks in published copy. Do not call Tarka OSS in new docs. Keep `scripts/oss/` path names.
- Demo ≠ product. Product persists in Postgres. Demo uses the bundled seed file (limitation, not a second product).
- Visual builder stays `RequireRole` RiskArchitect. Registry **writes** use the same role. Reads use the same auth as `/v1/rules` GETs.
- Demo later / separate skin. Do not change `make demo`, fraud-desk compose, `SentencePackPanel`, or clone-demo.

## Why not keep today’s catalog as the register

`#377` made the desk and AI read one GET. Redis rows still appear because they are in the manifest, not because a buyer mapped them. A tenant cannot add `order_channel` without editing Python/JSON lists. A buyer key `txn_amt` does not become `amount` on evaluate.

The catalog GET stays. The **register** moves upstream of the join.

## Units

### 1. Registry row

| Field | Rule |
|-------|------|
| `name` | Unique per tenant overlay + global seed. `^[a-z][a-z0-9_]{0,127}$`. No `tx_` prefix. |
| `explanation` | Non-empty string, max 500 chars. Seed rows have one line each. |
| `source` | Exactly one of `tarka_core` \| `sdk_tarka` \| `mapped_buyer` \| `enrichment` \| `new_feature`. |
| `buyer_key` | Optional. Present on the **map**, not duplicated as a second identity on the row. A row may be the target of many maps. |

Seed (bundled `field_registry_v1.json`, `source: tarka_core`):

- every `counter_manifest_v1.json` `feature_outputs[].name`
- every `PAYLOAD_FIELDS` name in `author_catalog.py`
- every `IDENTITY_FIELDS` name that is not already in those two lists

Do not seed growth names or hop etypes.

Tenant rows **overlay** the seed. List = seed ∪ tenant rows (tenant wins on same `name`). Tenant cannot delete or rename a `tarka_core` seed name (400). Tenant may add `new_feature` / `mapped_buyer` / `enrichment` / `sdk_tarka` rows.

### 2. Map

`(tenant_id, buyer_key)` → `registry_name`.

- `buyer_key` is the ingest/payload key as received (preserve buyer spelling; do not slug it).
- `registry_name` must already exist (seed or tenant row). Mapping to an unknown name is 400 — create the registry row first (usually `source: new_feature` or `mapped_buyer`).
- One buyer key → one name. Last upsert wins.
- Two buyer keys may map to the same name.

### 3. Store

One interface used by APIs, catalog join, and evaluate remap:

- **Product** (`DATABASE_URL` is Postgres): tables `field_registry` (tenant overlay rows) and `field_maps`. Alembic revision after current decision-api head (`20260510_009`).
- **Demo / tests / SQLite:** read seed file. Tenant maps live in `field_maps` when the engine has the table (`Base.metadata.create_all` / SQLite tests); if the file-only path has no DB, maps are the optional `maps` array in the seed file. Document: demo recreate without a volume **drops** tenant maps. That is a limitation, not a second API.

Empty overlay + intact seed is the normal start. An operator who deletes the seed file gets an empty seed → catalog redis/payload from seed fail closed to `[]` for those groups; hops/growth stay `#377` behavior. Log once. Do not invent names.

### 4. API (decision-api)

Same router family as `/v1/rules` (desk-auth, not the internal counters token).

| Method | Path | Does |
|--------|------|------|
| `GET` | `/v1/fields` | Seed ∪ tenant overlay. Query `tenant_id` required. |
| `GET` | `/v1/fields/{name}` | One row. 404 if neither seed nor overlay. |
| `PUT` | `/v1/fields/{name}` | Upsert overlay (`explanation`, `source`). Reject `tarka_core` overwrite of seed identity; reject `tx_` names; reject bad `source`. |
| `GET` | `/v1/fields/maps` | Tenant maps. `tenant_id` required. |
| `PUT` | `/v1/fields/maps` | Body `{ buyer_key, registry_name }`. |
| `POST` | `/v1/fields/discover` | Body `{ tenant_id, payload }`. |

`POST /v1/fields/discover` returns:

```json
{
  "already_named": ["amount"],
  "mapped": [{ "buyer_key": "txn_amt", "registry_name": "amount" }],
  "candidates": [{ "buyer_key": "order_channel", "suggested_source": "new_feature" }]
}
```

- `already_named` — payload key equals a registry name.
- `mapped` — payload key has a map.
- `candidates` — payload key is neither. Do not auto-insert rows.

Route order: register `/v1/fields/maps` and `/v1/fields/discover` **above** `/v1/fields/{name}` (same lesson as `author-catalog` vs `{filename}`).

Writes: RiskArchitect. Demo skin: GET + discover allowed; PUT returns 403 with copy that maps persist on product Postgres (do not silently write the seed file in the demo image).

### 5. Catalog join (the only catalog change)

`build_author_catalog` gains registry names (from seed ∪ tenant overlay for the request tenant). If tenant is missing on the catalog GET, use seed only (today’s public catalog).

```
redis   = manifest feature_outputs whose name ∈ registry
payload = (PAYLOAD_FIELDS ∩ registry) ∪ overlay names that are not redis names
          IDENTITY seeds stay on ai_allowed_fields; they do not flood the picker
growth  = #377 (graph URL + policy). Not filtered by registry.
hops    = #377 CATALOG_HOPS. Not filtered by registry.
```

GET `/v1/rules/author-catalog` stays. Add optional `tenant_id` query so the desk join includes overlay names. Omit / empty → seed-only (demo and first paint stay identical to `#377` until a tenant overlay exists).

Do not add windows, thresholds, or etypes to registry JSON.

`ai_allowed_fields` = catalog field names ∪ `IDENTITY_FIELDS` ∪ `LEGACY_ALIASES` (unchanged union). New `new_feature` overlay names appear in `payload` and therefore in the allow-list.

### 6. Evaluate remap

One function, one call site, before `compute_features` and before payload extras (`amount` / `currency` copies) read `body.payload`:

- Copy `body.payload` to a working dict.
- For each tenant map, if `buyer_key` is present and `registry_name` is not already set, set `registry_name` to that value.
- If both keys are present, **registry name wins** (do not overwrite an explicit `amount` with `txn_amt`).
- Do not delete the buyer key. The working dict may contain both `txn_amt` and `amount`.
- Missing buyer key → do not invent the registry name (sum/avg/distinct stay on “field present,” same as `#377`).
- Do not write `0` for a missing mapped field.
- Do not add `registry_id` or a parallel features object.

Apply maps to `body.payload` in-memory for this evaluate only. Audit `payload_snapshot` stores that working dict (buyer keys kept; registry names added). Receipts then match what Redis and packs saw.

No map rows → evaluate is a no-op vs `#377`.

### 7. Pack author reject

Human `POST`/`PUT` `/v1/rules` and AI `_validate_ai_authored_pack` reject `when[].field` not in `ai_allowed_fields(live catalog for tenant)` with 422:

`unknown field '{field}'; map it or add a registry row`

`when_ast` hop atoms are unchanged (etype allow-list stays `#377`; not a registry check).

Evaluate **does not** refuse to run an already-stored pack whose field is unknown. Missing feature → condition false, as today.

`pack_author_contract.validate_ai_authored_pack` takes `allowed_fields`. Import-time `ALLOWED_FIELDS` is seed ∪ identity ∪ aliases only (`ponytail:` ceiling: shadow_agent process without a tenant GET). Decision-api write path always passes the live set. A tenant `new_feature` that only exists in Postgres is authorable through decision-api; it is not authorable through a cold shadow_agent import. Document that. Do not add a shadow_agent → registry HTTP client this slice unless the write already goes through decision-api (it does for scout leftovers).

### 8. Desk (product only)

Thin panel on `/rules` (not a new nav item, not `/cases`):

- lists `GET /v1/fields` (name, source, explanation)
- discover box: paste JSON → `POST /v1/fields/discover`
- map a candidate: `PUT /v1/fields/{name}` if needed, then `PUT /v1/fields/maps`

Hidden on `DESK_PROFILE=demo`. Visual Feature picker and leftover seed keep consuming the catalog GET; they do not grow a second list.

### 9. Docs

Add `docs/docs/guides/field-registry-onboarding.md`:

- seed vs overlay
- map then author
- discover → candidate → row → map
- demo limitation (file seed, no durable maps)
- empty/missing seed → catalog redis/payload empty; hops/growth unchanged
- `tx_*` aliases are migrate-only
- pointers to `counter_manifest_v1.json` (windows) and graph growth policy (not this table)

One paragraph on `PACK_AUTHOR.md`: unknown field → map workflow, not silent drop. Do not rewrite PACK_AUTHOR as a feature-store guide.

## Error handling

| Case | Behavior |
|------|----------|
| Unknown registry name on GET | 404 |
| PUT seed `tarka_core` rename/delete | 400 |
| Map to missing registry name | 400 |
| `tx_*` new name | 400 |
| Bad `source` / empty explanation | 422 |
| Demo PUT | 403 + limitation copy |
| Catalog GET without tenant | seed-only join (same redis/payload as `#377` day-1) |
| Discover non-object payload | 422 |
| Evaluate remap, no maps | identical to `#377` |
| Postgres down on product list | 503; do not fall back to inventing names. Catalog GET seed-only if overlay load fails (log). Hops/growth still `#377`. |

## Tests

- Seed names include `event_count_7d`, `avg_amount_1h`, `amount`. Do not include `relation_growth_1h` or `USES_DEVICE`.
- Overlay `order_channel` + catalog GET with that tenant → `payload` contains `order_channel`; redis still only manifest ∩ registry. Seed-only catalog `payload` does not list `entity_id`.
- Manifest name removed from a test registry overlay → that redis row disappears from catalog; hops/growth unchanged.
- Map `txn_amt` → `amount`; evaluate payload `{txn_amt: 9}` → `compute_features` sees `amount` (sum/avg path). Payload `{amount: 4, txn_amt: 9}` → `amount == 4`.
- Discover `{txn_amt: 1, order_channel: "web"}` with that map → `mapped: txn_amt`, `candidates: order_channel`.
- PUT `tx_count_1h` as a new row → 400. Pack `when.field=tx_count_1h` still allowed (legacy alias).
- Pack `when.field=not_a_field` on POST `/v1/rules` → 422 with map copy. Existing on-disk pack with a weird field still evaluates.
- `/v1/fields/maps` is not captured as `{name}`.
- Demo PUT map → 403. Product PUT map persists on Postgres (test DB).
- Author catalog tests from `#377` still pass on seed-only GET (no tenant).
- Policy-check / ingest contract: remap is in-memory; missing mapped key does not insert `0`.

## Non-goals

- P-reg2 baseline assists / z-score / ratio keys.
- P-ing1 event taxonomy, SDK missing≠false, vendor enrichment ingest.
- P-graph1 hop sentence honesty / `sibling_prior_flag` UI.
- P-obs1 calibration window / scout map-unknowns beyond this allow-list reject.
- P-left1 first-class leftover object.
- P-day1 `desk_provision.json`, product `shadow_agent` overlay.
- P-enf1 webhooks / notify.
- `desk_provision`, Feast, ClickHouse `feature_definitions` reuse.
- New hop etypes. New growth windows. New Redis kinds.
- Attaching registry UUIDs on evaluate. Changing Rust.
- Demo Hunt / sentences / clone-demo / `make demo`.

## Done when

On a product image branched from `#377`: seed registry names match today’s catalog redis+payload+identity; a tenant can add `order_channel`, map `txn_amt` → `amount`, see `order_channel` on the author catalog, and evaluate uses remapped `amount` for Redis. Unmapped keys show up as discover candidates. Packs cannot author a ghost field. Growth and hops are still the `#377` lists, not registry rows. Demo still uses the seed file and refuses durable map writes. Windows still live only on `counter_manifest_v1.json`.
