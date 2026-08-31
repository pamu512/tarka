# Hunt significance expand

Locked 1 Sep 2026. Meet investigation-graph par, stay ahead via evaluate ranking.

## Goal

Hunt grows like an investigation graph (selective expand, caps, receipt lookback) and ranks like a fraud OS (attend / outcome / leftover Decision), not alphabet or degree.

## Seed (automatic)

Person (or leftover `/graph?entity_id=`) opens with a small ring:

- Durable instruments only: Device, Place, Payment, Ip, Document, LicensePlate, Email, Phone, Card, Address
- At most one Decision (latest visible / leftover if `decision_id` is on the URL)
- No Login or Session auto-dump
- Cap 25, ranked: `attend_pack` > attention importance > deny/review/flag > recency
- Place is a Hunt object (`SEEN_AT` / `cell:…`) when evaluate had lat/lon

## Expand (the verb)

Double-click or Expand uses a net, not “all types +1”:

- Types (default: durable + Decision)
- Optional relationship
- Max neighbors (default 25)
- Lookback (default 90 days) on Login / Session / Decision; durable types ignore lookback unless the analyst sets a type that is a receipt
- Widen lookback up to retention (`GRAPH_MAX_LOOKBACK_DAYS`, default 2555)
- Undated receipts stay (do not hide undated evidence)

## Scene filter

Sidebar types are multi-select hide/show on the loaded canvas. Changing them does not refetch.

## Query

`GET /v1/subgraph` accepts `lookback_days` and `types`. Filter after the AGE hop (AGE 1.6 has no reliable date predicate). Seed node always kept. Rank + `max_nodes` stay on the client (attention lives on `/links`).

## Identifier instruments (ATO / sold account)

Queryable params are vertices, not Person-only properties. Email / phone / document / card / address MERGE like Device. Two Persons stay two Persons. Expand the mailbox to see both. Person still carries current email/phone for display. `search_keys` indexes the instrument so a later evaluate cannot steal the mailbox.

## Out of scope

Most/least connected, timeline slicer, dump-then-group collections, deep entity-resolution hops, Person merge, global refetch-the-world form as the main verb.
