# Field registry onboarding (P-reg1)

A feature exists in Tarka because onboarding **mapped** a buyer payload key onto a **registry name** (plus a short explanation). The author catalog, evaluate remap, and pack allow-list all read from that register — not from ad hoc manifest copies.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). Self-hosting on your own metal or VPC for your own operations is allowed; providing Tarka to third parties as a hosted or managed service is not.

Related: [Rule authoring](rules.md) · [Hop pack authoring](hop-pack-authoring.md) · `services/shadow_agent/PACK_AUTHOR.md`

**shadow_agent cold-import ceiling:** scout import allow-list is seed ∪ identity ∪ legacy `tx_*` aliases. Tenant `new_feature` rows in Postgres are authorable via decision-api, not via a cold `shadow_agent` import. Do not add a shadow_agent→registry HTTP client.

---

## Seed vs overlay

**Seed** — bundled `field_registry_v1.json` (`source: tarka_core`). Built from:

- every `counter_manifest_v1.json` `feature_outputs[].name`
- every `PAYLOAD_FIELDS` name in `author_catalog.py`
- every `IDENTITY_FIELDS` name not already in those lists

Growth names and hop etypes are **not** seeded.

**Overlay** — tenant rows in Postgres (`field_registry` table) on product images. List = seed ∪ overlay; overlay wins on the same `name`. Tenants may add rows with `source` in `new_feature`, `mapped_buyer`, `enrichment`, or `sdk_tarka`. They cannot delete or rename a seed `tarka_core` name (`FieldRegistrySeedLocked` → HTTP 400).

There is no `desk_provision.json` in this slice — provisioning stays manual via the APIs and desk panel below.

---

## Map then author

Rule packs reference **registry names**, not raw buyer keys. Before you author `when[].field`:

1. Ensure the registry name exists (seed or overlay row).
2. Map each buyer ingest key to that name.
3. Confirm the name appears on `GET /v1/rules/author-catalog?tenant_id=…`.
4. Author the pack.

Unmapped payload keys never silently become pack fields. `POST`/`PUT` `/v1/rules` and AI pack validation reject unknown fields with HTTP 422:

`unknown field '{field}'; map it or add a registry row`

Already-stored packs with a stale field still evaluate (missing feature → condition false). See `PACK_AUTHOR.md` for the AI contract.

---

## Discover → candidate → row → map

Use discovery on a sample payload before creating rows:

```http
POST /v1/fields/discover
Content-Type: application/json

{
  "tenant_id": "your-tenant",
  "payload": { "txn_amt": 9.99, "order_channel": "web" }
}
```

Response buckets:

| Bucket | Meaning |
|--------|---------|
| `already_named` | Payload key equals a registry name (e.g. `amount`). |
| `mapped` | Payload key has a tenant map (e.g. `txn_amt` → `amount`). |
| `candidates` | Neither — suggested `source: new_feature`; **not** auto-inserted. |

Workflow for each candidate:

1. `PUT /v1/fields/{name}` — create overlay row (`explanation`, `source`).
2. `PUT /v1/fields/maps` — body `{ "tenant_id", "buyer_key", "registry_name" }`. Target name must already exist (`FieldRegistryUnknownName` → HTTP 400).

On product `/rules`, the **Field map** panel (RiskArchitect) lists `GET /v1/fields`, runs discover, and upserts rows/maps. Hidden when `TARKA_DESK_PROFILE=demo`.

Registry **writes** require RiskArchitect (same role as visual builder). Reads use the same auth as `/v1/rules` GETs.

---

## Author catalog join

`GET /v1/rules/author-catalog` is unchanged in shape. Optional `tenant_id` includes overlay names in the join.

```
redis   = manifest feature_outputs whose name ∈ registry
payload = (PAYLOAD_FIELDS ∩ registry) ∪ overlay names that are not redis names
growth  = graph policy GET when GRAPH_SERVICE_URL is set (#377 behavior)
hops    = CATALOG_HOPS (#377 behavior)
```

Identity fields stay on `ai_allowed_fields` via `IDENTITY_FIELDS`; they do not flood the payload picker.

Omit / empty `tenant_id` → seed-only join (demo and first paint match pre-registry catalog until an overlay exists).

---

## Evaluate remap

Before Redis compute, evaluate copies `body.payload` and applies tenant maps in memory:

- If `buyer_key` is present and `registry_name` is not, set `registry_name` from the map.
- If both are present, **registry name wins** (explicit `amount` is not overwritten by `txn_amt`).
- Buyer keys are kept; audit `payload_snapshot` stores the working dict.
- Missing buyer key → do not invent the registry name or write `0`.

No map rows → evaluate is identical to pre-registry behavior.

---

## Demo vs product

| | Demo (`TARKA_DESK_PROFILE=demo`) | Product (Postgres `DATABASE_URL`) |
|---|----------------------------------|-----------------------------------|
| Registry seed | Bundled `field_registry_v1.json` (**file/fixture**) | Same seed file |
| Overlay rows | Not durable — seed file/fixture only | `field_registry` table (survives restart) |
| Maps | Not durable — seed file/fixture only | `field_maps` table (survives restart) |
| `GET /v1/fields`, discover | Allowed (seed fixture) | Allowed |
| `PUT /v1/fields/*`, `PUT /v1/fields/maps` | **403** — `maps persist on product Postgres` | Persists in Postgres |

Demo recreate without a volume **drops** any leftover tenant rows. That is a documented limitation, not a second API. Fraud-desk compose is unchanged — do not expect durable registry writes from `make demo`. PUT 403 is the demo write path.

---

## Empty or missing seed

If `field_registry_v1.json` is missing or invalid, seed load returns `[]` (logged once). Catalog **redis** and **payload** groups fail closed to `[]` for that tenant join. **Hops** and **growth** stay `#377` behavior — they are not filtered by the registry.

Do not delete the seed file in production images.

---

## What stays outside the registry

| Concern | Where it lives |
|---------|----------------|
| Counter **windows** (`window_seconds`) | `services/decision-api/src/decision_api/data/counter_manifest_v1.json` only |
| Graph **growth** windows / thresholds | `GET /v1/graph/growth-policy` (graph-service parses `GRAPH_GROWTH_WINDOWS`) |
| Hop etypes (`USES_DEVICE`, …) | `CATALOG_HOPS` in `author_catalog.py` — not registry rows |
| Legacy `tx_*` **aliases** | Read-only on `ai_allowed_fields` for existing packs |
| New `tx_*` registry names | **Rejected** on `PUT /v1/fields/{name}` (migrate-only naming) |

Do not add windows, baselines, hop etypes, or Feast / feature-store product surfaces to registry JSON.

---

## HTTP surface (decision-api)

Same router family as `/v1/rules` (desk auth).

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/v1/fields?tenant_id=` | Seed ∪ overlay |
| `GET` | `/v1/fields/{name}?tenant_id=` | 404 if absent |
| `PUT` | `/v1/fields/{name}?tenant_id=` | Upsert overlay; demo → 403 |
| `GET` | `/v1/fields/maps?tenant_id=` | Tenant maps |
| `PUT` | `/v1/fields/maps` | Body `{ tenant_id, buyer_key, registry_name }`; demo → 403 |
| `POST` | `/v1/fields/discover` | Payload key classification |

Route order registers `/maps` and `/discover` before `/{name}`.

---

## Operator checklist

1. Paste a representative payload into discover.
2. For each candidate, create a registry row then a map.
3. Refresh author catalog with `tenant_id` and confirm redis/payload entries.
4. Author or AI-generate packs only against names on the live allow-list.
5. On product Postgres, verify maps survive restart; on demo, treat maps as ephemeral.
