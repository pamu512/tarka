# Material Decision hop on Person (Plan B)

**Date:** 2026-08-31  
**Status:** Implemented (branch `feat/decision-age-hop`)  
**Related:** leftover Hunt production, hop v1.2, `decision_graph_payload.py`, `decision_graph_mirror.py`

Branched AGE wire (conversation `6f86a2c6`): evaluate upserts Person/Device/Payment/Login **and** a Decision that cites pack + trace; `RESULTED_IN` is the stamp on that moment; fail-soft; Hunt stands on the Person. Later the mirror **dropped** Decision vertices to avoid unbounded growth. That drop is a workaround. This spec puts Decision back and **caps allows**, instead of deleting the hop.

## Goal

Hunt can hop `Person -RESULTED_IN-> Decision`. Story is those hops. SQLite stays accountability SoR. Evaluate still never 503s on graph.

## Non-goals (this slice)

- Multi-source ingest / v2-ingest
- Markings enforcement (field is reserved)
- Leftover mint default flip
- Janus-only path, Decision-as-home, AGE `[*1..n]`

## Write

Two existing writers, one AGE type:

| Writer | `source` | When AGE gets a Decision |
|--------|----------|---------------------------|
| evaluate (`_graph_upsert` + payload) | `evaluate` | `deny` / `review` always; `allow` while Person has &lt; 20 allow Decision vertices (rolling) |
| Hold / resolve (`build_human_disposition_payload` + object mirror) | `disposition` | always |

```
Person  -RESULTED_IN->  Decision
Decision -BASED_ON->    Payment | Login | Document | LicensePlate | Device | Session | Ip
Decision -SUPERSEDES->  prior Decision   (already in SQLite edges; AGE when both vertices exist)
```

Decision properties: `kind`, `source`, `outcome`, `trace_id`, `created_at`, `markings: []`, pack/rule ids when known. Id: `dec:{trace_id}` for evaluate; recorded `external_id` for disposition.

Object mirror (`schedule_mirror`) defaults **on**. It must write Decision / `RESULTED_IN` / `BASED_ON`. Tests that forbade those hops are wrong and change.

Allow cap: after a new evaluate-allow Decision, drop the oldest allow Decision on that Person until count ≤ 20. Material vertices are never dropped. `ponytail:` K=20; upgrade is a time-partitioned Decision subgraph.

## Hunt

Depth-1 already returns neighbors. Links show Decision. Story **prefers** `RESULTED_IN` neighbors (outcome from the Decision node). Audit receipts are fallback only when there is no hop.

Clicking a Decision seeds Hunt on that id.

## Fail-soft (do not break)

- Pack still allow/deny/review. Graph miss → `graph:write_failed`, still decide.
- `entity_id` required. ALLOW still does not mint a leftover.
- `/decisions` stays the receipt drawer, not home.

## Later attach (do not build here)

- Second/third source = same upsert + `source=` (dispute reprocess).
- Leftover mint follows material Decision.
- Need-to-know reads `markings` on Decision.

## Verify

1. Payload: material evaluate includes Decision + `RESULTED_IN` + `BASED_ON`.
2. Mirror writes that Decision (review/deny).
3. 21st allow on one Person does not leave 21 allow Decision hops (oldest allow gone).
4. Disposition payload includes Decision + `RESULTED_IN`.
5. Hunt Story shows hop outcome without audit when `RESULTED_IN` is present.
