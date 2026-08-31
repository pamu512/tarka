# Leftover station + Hunt production bar (A+B)

**Date:** 2026-08-31  
**Status:** Shipped on `master`. Plan: `docs/superpowers/plans/2026-08-31-leftover-hunt-production.md` (do not re-execute as greenfield).  
**Related:** [graph investigation workspace](./2026-08-13-graph-investigation-workspace-design.md), [graph property search](./2026-08-13-graph-property-search-design.md), VISION.md, `frontend/src/config/leanNav.ts`

## Goal

Production leftover ops at **3.8** and production Hunt at **4.0**. The demo inherits those numbers only if it walks the production path. A seeded Person that looks good is a **3**.

Work **arrives** on a thin Leftovers list. Work **happens** on Hunt (`/graph`). CaseDetail stays SAR / dispute. ALLOW never opens a case.

## Scoring lock

| Kind | How we score |
|------|----------------|
| Production | Checklist in this spec. If a must-be-true row is missing, that dimension is not 4 / 3.8. |
| Demo | Same numbers only when every **Demo witness** in this spec is exercised. Seed theater without those witnesses is 3. |

Do not quote a vendor 4.x because the 5-min worked.

## Philosophy (unchanged)

- Decision-api / Rust packs remain sole allow/deny.
- Evaluate never waits on graph. Hunt is not SoR.
- Review is residual. ALLOW never becomes a case. `flag` does not mint a leftover.
- Home stays `/graph` when graph is on. `/cases` stays hidden in lean nav.
- Not a CRM. Not a Tarka consortium. Not AGE variable-length Cypher.

## In the tree

- `GET /v1/leftovers`, claim, `claimed_by` / `claimed_at`, `last_outcome`. Desk `/leftovers` (lean, graph on). `/cases` hidden in lean.
- Hold `POST /v1/entities/{id}/act` mints or reuses an open leftover, label `act:hold`, writes `last_act` on Person. Resolve writes `y_label`.
- Evaluate mints deny/review leftovers by default (`CASE_CREATE_ON_DENY_REVIEW` is opt-out).
- Hunt home `/graph`; Story + Hold on the Person pane.
- AGE search is `MATCH (n) WHERE tenant_id = …` then Python filter. AGE Cypher does not use property indexes (apache/age#2348).

## Non-goals

- Unhide fat `/cases` or port CaseDetail onto the pane.
- Next-unassigned auto-serve, multi-inbox routing, snooze, QA sampling (caps leftover at 3.8).
- Bulk-decision on every neighbor, consortium who-else (caps Hunt at 4.0).
- AGE `[*1..n]` / GIN-on-properties as the search fix.
- FinCEN ungating, no-code builder, Tarka-branded model.

---

## A — Leftover station (production 3.8)

### Leftover predicate

A case is a leftover when **all** are true:

1. `status` is `open` or `investigating`
2. `entity_id` is non-blank
3. Labels contain `act:hold` **or** `origin:evaluate`

Evaluate-born mint (`maybe_create_case_for_outcome`) **must** set `labels` to include `origin:evaluate` and store the evaluate `decision` on the case as `last_outcome` (new nullable string column). Hold mint keeps `act:hold` and does not clear `origin:evaluate` if both apply.

`flag` and `allow` never call that mint.

### Claim

New columns on `investigation_cases`:

| Column | Type | Rules |
|--------|------|--------|
| `claimed_by` | string(256), nullable | Actor id. Null = free. |
| `claimed_at` | timestamptz, nullable | Set when claimed. Null when free. |
| `last_outcome` | string(32), nullable | Evaluate decision or empty. Missing ≠ allow. |

Do not reuse `assigned_team` or `default_owner` for claim.

**Claim rules**

- `POST /v1/leftovers/{case_id}/claim` with `tenant_id`. Actor = current user id.
- Same actor, already claimed → 200, no-op.
- Other actor → **409** `{ "detail": "claimed", "claimed_by": "…" }`.
- Hold (`POST /v1/entities/{id}/act` action `hold`) claims if free; 409 if claimed by someone else (Hold does not steal).
- Navigating from the Leftovers row to Hunt **claims if free** (frontend calls claim, then opens `/graph?entity_id=`). Opening Hunt via search/typeahead does **not** claim.
- Release: `POST /v1/entities/{id}/act` action `release` clears `claimed_by` / `claimed_at`, sets Person `last_act=released`, case stays open. Only the claimer or a role that already may update the case.
- Resolve: `POST /v1/entities/{id}/act` action `resolve` with `reason_code` from the existing `DISPOSITION_REASON_CODES` map (`CONFIRMED_FRAUD`, `FALSE_POSITIVE`, …). Sets case status via `escalate_status_for_reason`, Person `last_act=resolved`, pushes y_label on the leftover’s `trace_id` through `_persist_disposition_y_label`. Stays on Hunt. 400 if `reason_code` missing or unknown.

### List API

`GET /v1/leftovers?tenant_id=&free_only=0`

Auth: same as case list (`analyst` or insecure desk).

Returns leftovers for that tenant, newest `updated_at` first, limit 100.

```
{
  "leftovers": [{
    "case_id": "uuid",
    "entity_id": "str",
    "origin": "hold" | "evaluate" | "both",
    "last_outcome": "deny" | "review" | null,
    "last_act": "held" | "released" | "resolved" | null,
    "claimed_by": "str" | null,
    "sla_breached": bool,
    "trace_id": "str"
  }],
  "truncated": bool
}
```

`origin`: `both` if labels include both `act:hold` and `origin:evaluate`.  
`last_act`: from the latest human disposition for that entity if cheap; else `held` when `act:hold` and still open, `null` otherwise. Do not call graph-service from this list (fail-soft: leftover list must work if graph is down).

`free_only=1` keeps rows with `claimed_by` null.

SLA uses existing `is_sla_breached` / case SLA fields.

### Desk

- New lean path `/leftovers`. Add to `LEAN_NAV_PATHS`. Visible in lean when graph is on (same gate as Hunt: leftovers without Hunt is a ticket queue — hide if graph URL empty).
- `/cases` stays hidden. `/cases/:id` stays registered for SAR / dispute / QA.
- Page is a table of the list API. Row click: claim (if free) → `/graph?entity_id=&tenant_id=`. Claimed-by-other rows are visible, not clickable as “work this,” show `claimed_by`.
- No KPIs, bulk labels, saved views, or CaseDetail chrome.

### Demo witnesses (A)

1. Evaluate deny or review with mint on creates a leftover (`origin:evaluate`). Open `/leftovers`, not `/cases`.
2. Hold creates or reuses a leftover (`act:hold`). List shows both origins.
3. Second session: claimed row is not free. Claim by other is 409.
4. Resolve on Hunt with `reason_code=FALSE_POSITIVE` (or `CONFIRMED_FRAUD`). Still on `/graph`. Case is terminal.

---

## B — Hunt (production 4.0)

### Search keys (SQL)

New table in **graph-service** Postgres (same DB AGE already uses):

| Column | Type |
|--------|------|
| `tenant_id` | string, not null |
| `entity_external_id` | string, not null |
| `key_kind` | `email` \| `phone` \| `external_id` |
| `key_norm` | string, not null (lower + strip) |
| `last_outcome` | string, nullable |
| `updated_at` | timestamptz |

Unique `(tenant_id, key_kind, key_norm)`.  
Btree `(tenant_id, key_norm)`.

**Write:** after a successful `upsert_entity` of Person (and Device `external_id` only), upsert search rows for `external_id` plus Person `email` / `phone` from properties. Copy `last_outcome` from properties when present. Same fail-soft as today’s graph write: evaluate does not wait; a failed search upsert is logged, not raised to the client.

**Do not** backfill historical vertices in this slice. Missing `last_outcome` is **unknown**.

### Search API

`GET /v1/entities/search` stays the path.

When the search table exists (AGE / lite / any graph-service with this Postgres):

1. Empty `q` (strip, max 256) → `{ "entities": [], "truncated": false }`, no scan.
2. `q` shorter than 2 characters → same empty 200.
3. SQL: `tenant_id = ? AND key_norm LIKE lower(q) || '%'`, order: outcome rank, then `entity_external_id`. Limit 20.
4. Outcome rank: `deny`, `review`, `flag`, **unknown** (null), then `allow`. Null is never sorted as allow.
5. Dedupe by `entity_external_id`. Prefer Person rows if the same id appears as Device (Person email/phone wins).
6. `truncated: true` if more than 20 matches exist.
7. **Do not** run AGE `MATCH (n)` for this path.

Neo4j / Janus: if the search table is populated (upsert always writes it), use the same SQL. If the table is empty (operator never migrated), keep the existing backend search as fallback and set `truncated: true` when that fallback scans. Production AGE does not use the fallback.

Identifier resolve (email → Person) is the `entity_external_id` on the email/phone row. No second full-tenant hop.

### last_outcome on the desk

- Person / Device header in `GraphContextPanel`: show `last_outcome` or the word **unknown**.
- Canvas node: paint deny/review/flag; unknown is a distinct state (not the allow color). Use stored property only. Do not live-score.
- Search typeahead: show outcome or unknown on the row.

### Fan-out cap

Keep `HUNT_HIERARCHY_EXPAND_CAP = 8`. Count instrument neighbors **before** the cap. If `N > 8`, show **Showing 8 of N instruments** on the canvas or pane (one place, pane is enough). Do not silently drop.

### Graph lag

On dossier load, call existing `graph.latestEvaluate`. If that receipt has a `trace_id` and it is not in `entityHistory.trace_ids` / does not equal `last_trace_id`, show **Graph lagged this evaluate. Receipt is source of truth.** Do not invent objects. Do not block Hold.

If `latestEvaluate` is 404 / null, no banner (nothing to compare).

### Demo witnesses (B)

1. Typeahead uses the Person **email**, not `entity_id`. Hit is the Person.
2. One Person with `last_outcome`, one without. Unknown is labeled, not painted as allow.
3. Fixture or seed with more than 8 instruments. Cap copy visible.
4. Fixture where latest evaluate `trace_id` ≠ object `last_trace_id`. Lag banner visible. Receipt still loadable.
5. Open `hunt-eval-buyer`: evaluate Story / pack-why on first paint (no regression).

---

## Architecture

```
evaluate deny/review ──(default on; CASE_CREATE_ON_DENY_REVIEW opt-out)──► case-api leftover
                                                              labels origin:evaluate
Hold / resolve / release ──► case-api act + claim + last_act
GET /v1/leftovers ──► thin /leftovers ──claim──► /graph?entity_id=

evaluate objects ──fail-soft──► graph upsert ──► AGE vertex
                                              └► search_keys SQL
GET /v1/entities/search ──► SQL prefix (AGE production)
GraphContextPanel ──► last_outcome | unknown
                   ──► latestEvaluate vs last_trace_id → lag
                   ──► 8 of N
```

## Files (implementation map, not the plan)

| Area | Files |
|------|--------|
| Leftover API | `services/case-api/src/case_api/main.py`, `models.py`, alembic, `tests/test_object_act.py` + leftover tests |
| Evaluate mint label | `services/decision-api` `maybe_create_case_for_outcome` / case-api create payload |
| Lean desk | `frontend/src/config/leanNav.ts`, new leftovers page, `GraphContextPanel.tsx` |
| Search table | `services/graph-service` upsert + `age_client.search` + alembic/SQL, `tests/test_entity_search.py` |
| Fan-out / lag / unknown | `frontend/src/domain/graphInvestigation.ts`, `GraphInvestigationPage.tsx`, `GraphContextPanel.tsx` |

## Test plan (spec-level)

- Case-api: leftover predicate; claim 200 / 409; Hold does not steal; resolve requires a known `reason_code`; ALLOW/flag do not mint; `origin:evaluate` on evaluate mint.
- Graph-service: empty/`q`<2 no scan; prefix hit; unknown sorts after flag and before allow; truncated; AGE search path does not contain `MATCH (n)` for the SQL path.
- Frontend: leftovers row → graph; claimed-other not worked; unknown label; 8 of N; lag banner; first-paint evaluate regression.

## Out of score (do not claim)

- Leftover **4.5** without claim routing / next-unassigned / QA.
- Hunt **4.2** without neighbor bulk-act and a network.
- Production 4.0 Hunt if search still scans or unknown is painted as allow.
- Production 3.8 leftover if evaluate cannot mint or two analysts collide.
