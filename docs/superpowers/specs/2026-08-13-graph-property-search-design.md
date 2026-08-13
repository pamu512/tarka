# Graph property search + identity resolve

**Date:** 2026-08-13  
**Status:** Approved  
**Related:** [graph investigation workspace](./2026-08-13-graph-investigation-workspace-design.md), [graph-service](../../docs/services/graph-service.md), OpenAPI `contracts/openapi/graph-service.yaml`

## Goal

Typing an email, device id, IP, phone, or card in Graph search finds the **identifier node and its neighboring Person / Account / User**, so the analyst can open the person without already knowing the graph id.

This spec extends the existing `GET /v1/entities/search` typeahead. It does not add a new page, index, or write path.

## Philosophy (unchanged)

- Decision-api / rules remain sole allow/deny. Stored `risk_score` is a feature, not a decision.
- Do not invent graph, nodes, paths, or scores when the graph plane is down.
- `0` is a computed clean score. Unscored nodes stay `scored: false`, `risk_score: null`.
- AI / Shadow do not gain a new tool. Search still returns stored risk only.

## What already exists

- `GET /v1/entities/search` matches case-insensitive **contains on `external_id` only**. Empty `q` → `[]`, no scan. Optional `label`. Limit clamp 1–50.
- Typeahead at `/graph` seeds canvas via existing subgraph load (`selectEntity`).
- Type chips set the search `label` param; they do not filter the canvas.
- Ingest already creates `Email` (`email`), `Device` (`device_id`), `IP` (`address`), `Card` (`card_id`), `Address` (`line1`) vertices and links them to `User`. Graph-service upserts always have `external_id`.
- Workspace spec explicitly deferred property-bag search; this spec is that follow-on.

## Approach (locked)

Query-time resolve on the three graph backends. No `search_keys[]` on write. No second HTTP hop from the UI.

## Constants (frozen, not tenant-configurable)

**Search properties** (string CONTAINS, case-insensitive), checked in this order for `matched_on`:

`external_id`, `email`, `device_id`, `address`, `line1`, `phone`, `ip`, `user_id`, `card_id`

`line1` is the Address ingest key (same reason `card_id` is listed).

**Identifier labels** (direct hits that also resolve neighbors):

`Email`, `Device`, `IP`, `Phone`, `Address`, `Card`

**Owner labels** (1-hop neighbors to also return):

`Person`, `Account`, `User`

**Fan-out:** at most **10** owner neighbors per identifier node.

## API

Same path, auth (`API_KEYS`), and query params as today:

| Param | Required | Rules |
|-------|----------|--------|
| `tenant_id` | yes | exact tenant match |
| `q` | no | strip; max 256. Empty or missing → `{ "entities": [] }` (200), no scan |
| `label` | no | applied **after** resolve: keep rows whose `labels` contain this string. Unknown label → `[]`, not 400 |
| `limit` | no | default 20, clamp 1–50 (after union + dedupe + label filter) |

### Match

Tenant nodes, excluding `GraphRiskStats`, where **any** allowlisted string property case-insensitive **CONTAINS** `q`. Parameterized queries only (Neo4j / AGE). Janus stays a full tenant vertex scan (ponytail: upgrade = mixed index on the allowlisted keys).

Skip any node whose `external_id` is missing or blank. Do not invent an id from `email` / `device_id`. Those vertices cannot seed `GET /v1/subgraph` today.

Non-string property values are ignored (not coerced, not stringified).

### Resolve

For each **direct** hit whose labels intersect identifier labels, take **1-hop** neighbors (any relationship type, both directions) whose labels intersect owner labels and who have a non-blank `external_id`. Cap 10 owners per identifier. Do not walk 2 hops. Do not restrict to named ingest rel types (`USED_DEVICE`, …).

### Dedupe

Union direct hits and resolved owners. Key = `entity_id` (`external_id`).

When the same id appears twice:

1. Prefer an owner-label row over an identifier-only row.
2. If one row has `via` and the other does not, keep `via` (subtitle needs it).
3. Keep the earlier `matched_on` in allowlist order.

### Rank

1. Owner-label rows first (`Person` / `Account` / `User` in `labels`).
2. Then `risk_score DESC` with unscored last (`NULL` / missing `risk_computed_at`).
3. Then `entity_id ASC`.

Slice to `limit`. Do not live-compute risk.

### Hit shape

Existing fields plus:

```
{
  "entity_id": str,
  "tenant_id": str,
  "labels": [str],
  "scored": bool,
  "risk_score": number | null,
  "matched_on": "external_id" | "email" | "device_id" | "address" | "line1" | "phone" | "ip" | "user_id" | "card_id",
  "via": null | { "entity_id": str, "labels": [str] }
}
```

- `matched_on`: first allowlisted property (order above) whose string value contained `q`. Resolved owners inherit the identifier’s `matched_on`.
- `via`: `null` on a direct hit. On a resolved owner, the identifier node’s `entity_id` + `labels`. If several identifiers resolved to the same owner, keep the first seen.

OpenAPI `EntitySearchHit` required: existing four plus `matched_on`. `via` may be null.

Backends: Neo4j, Janus, AGE — same contract.

## UI (`/graph` typeahead)

Placeholder: `Id, email, device, IP…`

Each row still clicks `selectEntity(hit.entity_id)` (existing seed subgraph). No extra request.

Row content:

- Line 1: `entity_id`, primary label (`labels[0]` or `Custom`), stored score if `scored`.
- Line 2, only when `via` is set: `via {via.labels[0]} {via.entity_id}`.

Example: query `alice@acme.com` with Email `alice@acme.com` linked to Person `user-441` → two rows, Person first, then Email. Click Person seeds `user-441`. Click Email seeds `alice@acme.com`.

Type chip `Person` + that query → Person row only. Chip `Email` → Email row only.

Debounce, stale abort, graph-plane disabled: unchanged.

Mocks and `graph.searchEntities` types include the new fields. Older mocks that omit them must still typeahead (treat missing `via` as none; missing `matched_on` as `external_id`).

## Errors

Unchanged fail-closed:

- Graph plane disabled: no search call.
- Backend 5xx: existing `searchErr`; empty list; canvas untouched.
- Unknown `label`: `[]`.
- Blank `q`: `[]`, no scan.
- Do not invent hits, `via`, or scores.

## Tests

Graph-service:

1. Direct: Email node, `email` CONTAINS `q`, has `external_id` → one hit, `matched_on=email`, `via=null`.
2. Resolve: that Email linked to Person → both hits; Person sorts first; Person `via.entity_id` is the Email; Email still present.
3. Chip: `label=Person` returns Person only; `label=Email` returns Email only.
4. Dedupe: Person has `email` prop **and** is 1-hop from Email node → one Person row (keep `via` if the identifier was also a hit).
5. Skip blank `external_id` even if `email` matches.
6. Unscored: `scored=false`, `risk_score=null` (not `0`).
7. Fan-out: identifier with 12 owner neighbors returns at most 10 owners from that identifier (plus the identifier itself if it is a direct hit), then global `limit`.
8. Neo4j / AGE source still parameterized (`$q`, no f-string interpolation of `q`). Janus source still tenant-scan (no fake index).
9. Empty `q` still `[]` with no store scan (existing HTTP test).

Frontend:

10. Typeahead subtitle renders when `via` is set; absent `via` has one line.
11. Click Person row calls seed with the Person `entity_id`.
12. Mock search hits include `matched_on` / `via` for the email→person fixture.

Docs: `docs/docs/services/graph-service.md` and `docs/docs/api-reference.md` describe property CONTAINS + resolve, not “id contains only”.

## Out of scope

- Elasticsearch, `search_keys` on upsert, or any new index
- Expand prune-toward-expanded-node (honesty-review item 2)
- Empty-state beyond top-20 scored (honesty-review item 3)
- Live risk overlay, AI-on-canvas, URL Back stack
- Inventing `entity_id` for ingest vertices that lack `external_id`
- New ingest edges or Phone vertices
- Changing seed depth, subgraph, or dossier
- Tenant-configurable search fields
