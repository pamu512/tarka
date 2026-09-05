# Leftover → Hunt → visual Observe pack (product)

**Date:** 2026-09-05  
**Status:** Design — approved in chat; not implemented.  
**Related:** [desk demo vs product](./2026-09-05-desk-demo-vs-product-design.md), [leftover Hunt production](./2026-08-31-leftover-hunt-production-design.md), `frontend/src/components/RuleBuilder/`, `frontend/src/utils/sentencePack.ts`, `services/decision-api/src/decision_api/data/counter_manifest_v1.json`

## Goal

Make Tarka easier to use: the field an analyst picks is a field evaluate actually fills.

On the **product** desk, leftover → Hunt → **Draft Observe pack** lands on the visual builder with leftover pack-why already applied. Save is Observe. Promote is not this slice.

Authors do not maintain five field lists. One catalog drives Redis counters, graph growth keys, the desk picker, leftover seed, and the AI allow-list. The canvas picker is **function-shaped** (count / sum / avg / distinct / growth / hop + window). The saved pack is still `when.field` or `when_ast` `has_etype` — no new Rust atom.

Demo skin, `make demo`, and `SentencePackPanel` stay unchanged until this product loop is done.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty plane URL = that plane off. No stub neighbors. Graph keys **absent** when the graph URL is empty (do not write `0`).
- Leftovers stay the queue. Work happens on Hunt. Do not unhide `/cases`.
- No `case.receipt_brief/v1`. No `rate` / `baseline_ratio`. No new Rust `velocity_v1`. No `velocity()` in pack JSON this slice.
- Visual builder stays `RequireRole` RiskArchitect. Missing role → existing `/403-unauthorized`.
- Leftover-sourced and visual **Save AST pack** stay Observe (`mode: shadow`). `POST /v1/rules` already forces shadow — do not add a live save path.
- Query-carry: Hunt stays Hunt. No canvas on the dossier.
- No named third-party desks in published copy.
- **Demo is out of scope.** Do not add Draft to the demo Hunt. Do not change fraud-desk compose, first-hour sentences, or clone-demo copy in this slice.
- No Feast / feature-store service. No desk settings UI for windows (env + GET only).
- Do not invent hop etypes. Canvas + leftover hop allow-list is exactly `USES_DEVICE`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_CARD`, `HAS_LIST`.
- Payload extras already on `/rules` (`device_type`, `is_bot`, `distinct_countries_7d`, …) stay as a frozen **payload** group. Do not add them to Redis compute. Do not invent new payload keys.

Implement on the product-profile branch (`feat/desk-demo-vs-product` / PR #377) so `DESK_PROFILE` exists.

## Why not keep today’s key process

`counter_manifest_v1.json` already names Redis outputs. `compute_features` does not read it. `/rules` `FIELD_CATALOG`, `VELOCITY_KEYS`, `PACK_AUTHOR` / `ALLOWED_FIELDS`, and `rule_api._AI_PACK_ALLOWED_FIELDS` are four more copies. They already disagree (`event_count_7d`, `avg_amount_*`, `distinct_session_id_24h` missing from the desk). Graph `relation_growth_*` is Hunt-only and hardcoded 5/15.

There is no product reason to keep that. Named keys stay as the **compile target**. The **register** is the catalog.

## How a new key is created (after this slice)

| Kind | What you change | What you do not change |
|------|-----------------|------------------------|
| Redis counter (count / sum / avg / distinct) | One row in `counter_manifest_v1.json` (`name`, `kind`, `window_seconds`, `field` when needed). Deploy. | Desk catalogs, sentences leftover-parse, AI allow-list, `compute_features` loops. |
| Graph growth window | `GRAPH_GROWTH_WINDOWS` on graph-service. Restart graph-service. | Frontend 1h/24h/5/15 literals, `VELOCITY_KEYS` hand edits, a second env on decision-api. |
| Hop etype | Still code (evaluate `PACK_HOP_ETYPES` + graph schema). **Not this slice.** | — |

Invalid manifest row (unknown `kind`, missing `name`, `window_seconds` ≤ 0 or > 30d) is skipped at load with a log line. Do not invent a key. Empty feature_outputs after skip → keep today’s eleven names as the built-in fallback so evaluate does not go blank.

Allowed window tokens for **growth** (and for author display of Redis windows): `5m`, `1h`, `6h`, `24h`, `7d` only. Redis rows may use any `window_seconds` the store already accepts (`MAX_WINDOW`); the catalog maps 300/3600/86400/604800 to those tokens and otherwise shows the seconds.

## Author catalog (one GET)

`GET /v1/rules/author-catalog` on decision-api (same auth as other `/v1/rules` reads). Not the internal counters token.

```json
{
  "redis": [
    { "name": "event_count_1h", "kind": "event_count", "window": "1h", "window_seconds": 3600 }
  ],
  "growth": [
    { "name": "relation_growth_1h", "kind": "growth", "window": "1h", "threshold": 5 }
  ],
  "hops": [{ "etype": "USES_DEVICE" }],
  "payload": [{ "name": "amount" }, { "name": "currency" }]
}
```

- `redis` = manifest `feature_outputs` (after skip of invalid rows).
- `growth` = `GET /v1/graph/growth-policy` mapped to `relation_growth_{window}` **only when** `GRAPH_SERVICE_URL` is set. Empty URL or policy GET fail → `growth: []`. Decision-api does **not** parse `GRAPH_GROWTH_WINDOWS` (graph-service is the only parser).
- `hops` = this exact list (one server constant the GET returns): `USES_DEVICE`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_CARD`, `HAS_LIST`. Product leftover parse and the hop node use the GET (bundled fallback = the same five). Do not expand to every evaluate `PACK_HOP_ETYPES` this slice. Demo `sentencePack.HOP_ETYPES` stays as it is.
- `payload` = today’s `/rules` extras that are not redis names (frozen).

Desk `/rules` `FIELD_CATALOG` and visual Feature picker **fetch this**. Leftover `parseVelocityField` accepts `redis[].name` ∪ `growth[].name`. AI `_AI_PACK_ALLOWED_FIELDS` / `ALLOWED_FIELDS` = catalog field names ∪ existing identity/SDK fields ∪ existing **legacy aliases** (`tx_count_*`, `tx_amount_*`, `distinct_devices_24h`, `distinct_ips_24h`). Do not drop aliases. Do not add `rate` / `baseline_ratio`.

If the catalog GET fails, the visual builder and `/rules` keep the last successful in-memory catalog for the session; first load failure → redis names from the bundled manifest JSON shipped with the SPA (copy of `feature_outputs` names only) + empty growth. Do not invent keys.

`GET /v1/internal/counters/manifest` stays for ops parity. It remains the Redis file. The author catalog is the desk-facing union.

## Redis compute reads the manifest

`AggregateStore.compute_features` (shared by decision-api fallback and counter-service) iterates `feature_outputs`:

- `event_count` → always compute `name`
- `sum` / `avg` → compute `name` only when `field` is present on the incoming feature map (same as today for `amount`)
- `distinct` → compute `name` only when `field` is present and truthy

`normalized_velocity_key_names()` returns manifest names in file order.

Existing test: compute keys match manifest when all branches apply — keep it; it becomes the driver, not a mirror check of two handwritten lists.

## Graph growth: config, query, evaluate keys

Today growth is hardcoded in graph-service (1h/24h counts), risk (`FAST_GROWTH_1H = 5`, `FAST_GROWTH_24H = 15`), and Hunt `growthOnly` (`>= 5` / `>= 15`). That is the bug.

**Config (graph-service only):** env `GRAPH_GROWTH_WINDOWS` default `1h:5,24h:15`. Each entry `{ window, threshold }`. Allowed tokens: `5m`, `1h`, `6h`, `24h`, `7d`. Invalid tokens dropped. Empty after parse → default pair. Decision-api and the desk read policy/counts over HTTP. Do not parse this env in the SPA or in decision-api.

**Queryable (graph-service)**

`GET /v1/graph/growth-policy` → `{ "windows": [{ "window": "1h", "threshold": 5 }, { "window": "24h", "threshold": 15 }] }`

`GET /v1/entities/{id}/relation-growth?tenant_id=&windows=1h,24h`

- `windows` optional. Empty / omitted → all configured windows.
- Unknown window token → omit that window (200), do not 400 the whole call, do not invent a count.
- Count = incident edges whose `coalesce(observed_at, created_at, updated_at)` is inside that window (UTC). Same rule as today’s 1h/24h. Untimestamped edges excluded from growth.
- Graph plane empty URL → Hunt does not call this (plane off).
- Response: `{ "entity_id", "tenant_id", "windows": [{ "window": "1h", "count": 3, "threshold": 5 }] }`. Missing entity → 200 with `count: null` (not 0).

Stored node fields `relation_growth_1h` / `relation_growth_24h` may remain for existing risk writeback. New reads do not assume only those two names.

**Evaluate:** after hop attach (`attach_hop_to_features`), if the graph plane is on, fetch relation-growth for the subject and copy each returned window onto the feature map as `relation_growth_{window}`. `count: null` → omit that key. Graph missing / unavailable / disabled → omit all growth keys (do not write 0). A real entity with zero edges in-window **does** get `0` so `gte` is false.

**Hunt (product)**

- Dossier (testid `node-relation-growth`): one line per returned window (`{window} {count ?? "—"}`; threshold as title/hint). No `1h`/`24h` literals in the component.
- Left-rail `growthOnly`: keep a node if **any** configured window’s count is ≥ that window’s threshold. Load policy once per Hunt session. No `>= 5 || >= 15` in `graphInvestigation.ts`.
- Risk scoring this slice: `FAST_GROWTH_*` for 1h and 24h read the matching configured thresholds. Do not add new score factors for extra windows (6h/7d).

## Why not seed Graph Risk

The canvas **Graph Risk** node compiles to `graph_score` / `graph_condition`. Leftover hops are `when_ast: { type: "graph_v1", atom: "has_etype", etype }` (same as `emitHopPack`). Seeding a hop leftover as Graph Risk would write the wrong atom. Growth leftovers seed a **Feature** node on `relation_growth_{window}`, not Graph Risk.

## Loop

```
/leftovers Work
  → /graph?entity_id=&tenant_id=&decision_id=&leftover_id=&pack=&hits=
  → Hunt dossier Draft Observe pack (product only)
  → /rules/visual?from=leftover&leftover_id=&pack=&hits=&etype=&field=
  → seed canvas → Save AST pack (shadow)
```

`etype` / `field` are set only when they parse to a catalog hop or a catalog redis/growth name. Otherwise those query params are omitted; the canvas opens empty with a leftover context banner.

## Units

### 1. Leftover Work query

**Today:** Work navigates to `/graph` with `entity_id`, `tenant_id`, `decision_id` (`dec:{trace_id}`).

**Add** (already on `LeftoverRow`; do not invent):

| Param | Source |
|-------|--------|
| `leftover_id` | `row.case_id` |
| `pack` | `row.pack_id` if non-empty |
| `hits` | `row.rule_hits` joined by comma if any |

Keep existing params. Hold-only leftovers with no pack still open Hunt; Draft still appears on product (empty seed).

### 2. Hunt Draft control

**Where:** `GraphContextPanel` dossier, next to existing Hold / pack-why. Not on the leftover table.

**Visible when:** `DESK_PROFILE === "product"` AND (leftover query `leftover_id` is set OR a pinned evaluate receipt is on the pane). Hidden on demo. Hidden if the graph plane is off (leftovers already hidden).

**Click:** `navigate` to `/rules/visual` with:

- `from=leftover`
- leftover_id / pack / hits copied from the Hunt URL when present
- `etype` if `parseHopEtype(...)` succeeds
- `field` if `parseVelocityField(...)` succeeds (redis **or** growth name from the catalog)
- `entity_id` / `tenant_id` / `decision_id` for a back-link

**Hop parse (first match, else omit `etype`):**

1. `pack_why.hop` from the pinned receipt / `resolvePackWhy` when it matches `has_etype:{ETYPE}` and `ETYPE` is in catalog `hops`.
2. Else a `hits` token that equals a hop etype, or `has_etype:{ETYPE}`.

`graph:missing` / `graph:unavailable` / `graph:empty` → no `etype`. Do not invent a hop.

**Field parse:** a `hits` token or pack stem that equals a catalog `redis` or `growth` name. Else omit `field`. If both hop and field parse, prefer hop (`etype` wins; drop `field`).

Copy: **Draft Observe pack**. Do not say Promote.

403: Draft is still shown; the visual route gate handles role.

### 3. Hop etype canvas node (product authoring)

Add one palette node, allow-list catalog hops only.

- Compile / save `when_ast`: `{ type: "graph_v1", atom: "has_etype", etype }` — same shape as `emitHopPack`.
- Tags on the saved rule: `FLAG` and `graph:has_etype:{ETYPE}` (same as sentences).
- Do not compile this node to `graph_score` or `graph_condition`.

Wire: Hop etype → Rule root (same handle rules as Graph Risk → root). No new evaluate runtime.

### 4. Visual picker (function sugar) + leftover seed

`/rules/visual` loads the author catalog. The Feature palette is grouped by `kind`: **Count**, **Sum**, **Average**, **Distinct**, **Growth** (growth group hidden when `growth` is empty). Each row shows window + name; save still writes `when.field = name`. Hop stays the hop node.

`/rules` form picker uses the same catalog (redis + payload + growth when present). Do not hand-edit `FIELD_CATALOG`.

`/rules/visual` reads the query when `from=leftover`.

**Seed** (`seedCanvasFromLeftover`):

- `etype` present → Rule root + Hop etype node, wired, etype selected.
- else `field` present → Rule root + Feature (`field`) + Operator (`gte`, value `0` placeholder the analyst must edit) + wires. Value `0` is a canvas default, not a claimed leftover threshold.
- else empty default canvas.

Banner (testid `leftover-visual-banner`): leftover id, pack id or `missing`, hits or `—`. If neither etype nor field: “No shipped hop or catalog key on this leftover — pick from the palette.” Back link to Hunt with the same entity/decision/leftover params.

**Save from `from=leftover`:** existing `rules.create` (server writes `mode: shadow`). Success copy: “Saved as Observe draft. Promote is not here.” Do not call `force-live` or `set_pack_mode(active)`.

Persist-target updates stay as today (also shadow on PUT).

## Error handling

- Graph URL empty → leftovers hidden; no Draft; catalog `growth: []`; evaluate has no `relation_growth_*`.
- Leftovers API down → existing fail-close; no Work.
- Unknown / missing leftover_id on visual → still open builder; banner says leftover context missing; no invented seed.
- Unknown etype/field in query → ignore (treat as absent).
- Visual without RiskArchitect → 403. Hunt Draft does not hide for that (no persona shell).
- Save 409 / 422 → existing error surface; pack stays unsaved.
- Catalog GET fail → bundled redis names + empty growth; banner not required.
- Invalid `GRAPH_GROWTH_WINDOWS` tokens dropped; empty parse → default `1h:5,24h:15`.

## Tests

- Leftover Work URL includes `leftover_id` + `pack` + `hits` when the row has them.
- Product Hunt shows Draft when `leftover_id` is on the query; demo Hunt does not (`DESK_PROFILE=demo`).
- `parseHopEtype("has_etype:USES_DEVICE")` → `USES_DEVICE`; `graph:missing` → null; `has_etype:FAKE` → null.
- `parseVelocityField` only returns catalog redis/growth names (includes `event_count_7d` and `relation_growth_1h` when those are in the catalog fixture).
- Hop node compile equals `emitHopPack` `when_ast` + FLAG tags.
- Visual `from=leftover&etype=HAS_LIST` seeds a HAS_LIST hop node; `etype=NOPE` does not seed a hop.
- Visual `from=leftover&field=relation_growth_1h` seeds a Feature on that field when the catalog fixture includes it.
- Leftover save success copy mentions Observe, not Promote. Created pack `mode === "shadow"`.
- RequireRole on `/rules/visual` still 403. Do not regress `audit_prod_desk_mocks` / leftover fail-close.
- `compute_features` emits a new manifest row’s `name` when that row is added in the test fixture (and does not emit a skipped invalid row).
- Author catalog: graph URL empty → `growth` empty; URL set + default windows → `relation_growth_1h` and `relation_growth_24h` present.
- Evaluate: graph URL empty → feature map has no `relation_growth_*`. Graph on + growth `count: 3` for `1h` → `features["relation_growth_1h"] == 3`. `count: null` → key absent.
- Hunt `growthOnly` uses policy thresholds from the GET, not literals 5/15.
- `/rules` picker lists `event_count_7d` and `avg_amount_1h` from the catalog (no hardcoded `FIELD_CATALOG` hole).

## Non-goals

- Demo Hunt Draft, sentences, clone-demo, `VITE_DESK_PROFILE=demo`.
- Observe → Promote inbox / notify cards (slice 3).
- Role-first workspaces.
- Unhiding `/cases`.
- Teaching Graph Risk to emit `has_etype`.
- New Day-1 `shadow_agent` overlay. Keys never in the SPA.
- Pack JSON `velocity(entity, window)` / new Rust `velocity_v1`.
- Feature-store product, backfills, training snapshots.
- New risk-score factors for 6h/7d growth.
- New hop etypes beyond the shipped canvas list.

## Done when

On a **product** image: leftover Work → Hunt → Draft Observe pack → visual builder seeded from a catalog hop, redis key, or growth key (or honest empty + banner) → Save is an Observe pack. `/rules` and the visual picker show the same catalog evaluate fills. Adding a manifest row or a `GRAPH_GROWTH_WINDOWS` token does not require editing desk field lists. Demo Hunt is unchanged. Promote is still a later slice.
