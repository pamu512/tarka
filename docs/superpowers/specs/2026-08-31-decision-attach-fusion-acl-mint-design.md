# Decision attach: fusion, markings ACL, leftover mint

**Date:** 2026-08-31  
**Status:** Building on `feat/decision-age-hop`  
**Spine:** [Material Decision hop](./2026-08-31-decision-age-hop-design.md)

Not a second graph. Same Person. Same Decision type. Third writer and ACL read the hop we just put back.

## Goal

1. Two live writers land on one AGE Person (evaluate + dispute/ingest).
2. Hunt reads Decision markings deny-by-default.
3. Material evaluate (deny/review) mints a leftover by default. ALLOW / flag never.

## Write

| Writer | `source` | How |
|--------|----------|-----|
| evaluate | `evaluate` | default |
| ingest (`map_tx_to_evaluate_request`) | `ingest` | stamps `metadata.decision_source` |
| dispute reprocess | `dispute` | stamps `metadata.decision_source` |
| Hold / resolve | `disposition` | already |

`attach_decision_object` reads `metadata.decision_source` (allowlist: evaluate, ingest, dispute, disposition). Same `entity_id` → same Person. Same hops: `RESULTED_IN`, `BASED_ON`, `SUPERSEDES`.

Not v2-ingest compose. Not a new vertex type.

## Markings

Write default: `markings: ["desk"]`. Empty markings on a Decision means hidden.

Hunt GET (`/entities`, `/links`, `/history`, `/subgraph`, `/deep-context`): header `X-Graph-Markings`. Visible iff caller ∩ node markings is non-empty. No header → no Decision nodes. Seeding a Decision you cannot see → 404.

Evaluate / risk `query_subgraph` stays unfiltered (pack still decides).

Desk `fetch` sends `X-Graph-Markings: desk`.

`ponytail:` one clearance (`desk`). Upgrade is per-tenant marking catalog + role map.

## Leftover mint

Mint leftover when evaluate outcome is material (`deny` / `review`) and `case_api_url` is set. `CASE_CREATE_ON_DENY_REVIEW` is an opt-out (`0`/`false`). Unset / lite default is **on**.

ALLOW and `flag` still never mint. Hold still mints `act:hold`.

## Fail-soft

Pack still decides. Graph miss → `graph:write_failed`. ACL miss is 404 / omitted hop, not 503.

## Verify

1. Dispute evaluate body has `decision_source=dispute`; ingest map has `ingest`; both attach on the same Person id.
2. Decision without intersecting markings is omitted from links/subgraph; Decision seed 404s.
3. Review/deny enqueue leftover mint when the flag is unset; allow/flag do not.
