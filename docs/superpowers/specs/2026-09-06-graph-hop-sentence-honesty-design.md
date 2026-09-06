# Graph hop sentence honesty (P-graph1)

**Date:** 2026-09-06  
**Status:** Design — cut locked in chat (`go`).  
**Branch:** `honesty/graph-hop-sentence-honesty` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** `frontend/src/utils/sentencePack.ts`, `services/decision-api/rules/graph_v1_uses_device_v1.json`, `docs/docs/guides/hop-pack-authoring.md`

## Goal

Evaluate already has `has_etype` and `sibling_prior_flag`. Desk sentences and the visual hop compiler must expose both, with honest copy. A trust sentence cannot emit bare `has_etype` while claiming sibling FLAG.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW. Model never Promotes.
- Empty `GRAPH_SERVICE_URL` = hops off. Receipt `graph:missing`. No invented neighbors.
- No `rate` / `baseline_ratio`. No new Rust atom. No new hop etypes. No `desk_provision.json`.
- Demo ≠ product. Visual builder stays RiskArchitect.
- No named third-party desks in published copy. Do not call Tarka OSS.
- **Two sentences** (not one AND-only, not copy-only):
  - **Share-edge** — `has_etype` only. No `FLAG` tag. Copy does not say sibling / trust FLAG.
  - **Trust FLAG** — same `when_ast` as shipped packs: `has_etype` AND (`has_multi_id` OR `sibling_prior_flag`). `FLAG` tag. Copy names sibling prior FLAG.
- Hop catalog / sentence consts stay the signed five: `USES_DEVICE`, `HAS_EMAIL`, `HAS_PHONE`, `HAS_CARD`, `HAS_LIST`.
- Graph = identity hop (AGE / `GRAPH_SERVICE_URL`). Decision-context SQLite is not the Graph SKU.

## Why now

`emitHopPack` and `compileHopEtypeFromCanvas` emit `{ atom: "has_etype" }` with `tags: ["FLAG", …]` and copy “FLAG when this person shares”. Shipped Observe packs already require the trust AND. Atoms and `pack_why` already name `sibling_prior_flag`. The lie is the desk emitter, not evaluate.

Rejected: one sentence that always ANDs (hides share-edge). Rejected: copy-only (still no sibling path).

## Units

### 1. Sentence emitter

`HopSentence` gains `kind: "share" | "trust"` (default `"share"`).

Share: `when_ast = { type: "graph_v1", atom: "has_etype", etype }`. Tags: `graph:has_etype:{etype}` only. Description: shares this etype.

Trust: `when_ast` matches `graph_v1_uses_device_v1.json` (etype swapped). Tags: `FLAG` + `graph:has_etype:{etype}`. Description names sibling prior FLAG.

Unknown etype still falls back to `USES_DEVICE` (today’s const guard).

### 2. Desk + visual compiler

`SentencePackPanel` hop row: etype select + kind select (share-edge / trust FLAG).

`HopEtypeNode` optional `kind` (default share). `compileHopEtypeFromCanvas` calls `emitHopPack` so canvas JSON matches the sentence.

### 3. Docs split

`hop-pack-authoring.md`: both sentences; Graph = identity hop; decision-context SQLite ≠ Graph SKU. One line on `architecture.md` / `decision-context-graph.md` if they still call decision-context “the Graph”. Do not rewrite the decision-context guide.

## Error handling

- Empty graph URL unchanged (`graph:missing`, pack must not FLAG). Trust sentence still does not fire without hop data.
- Unsigned / unknown etype: compiler `ok: false`; sentence emitter stays on signed list.

## Testing

- Share emit: atom `has_etype`, no `FLAG` tag, description has no “sibling”.
- Trust emit: AND tree includes `sibling_prior_flag`; has `FLAG` tag.
- Canvas compile equals `emitHopPack` for both kinds.
- Existing hop pack atom / `graph:missing` tests still pass.
- Catalog hops still the signed five.

## Success

Trust sentence cannot emit bare `has_etype` while claiming sibling FLAG. Share-edge does not mint FLAG. Docs do not call decision-context SQLite the Graph SKU.

## Non-goals

- New etypes. New Rust atom. Leftover-station hop chip rewrite. P-obs / P-left / `desk_provision.json`.
- Changing shipped `graph_v1_*` JSON packs (already honest).
- Opening a second Graph product.

## Done when

On a branch stacked on `#378`: two hop sentences; visual compile matches; docs name the split; atom / missing-hop tests still pass.
