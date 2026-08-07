# Marketplace P1 — Payout hardening design

**Date:** 2026-08-07  
**Branch base:** `master` @ `cb8d604d` (post Marketplace P0 merge)  
**Status:** Implemented (2026-08-07)  
**Predecessor:** [`2026-08-07-marketplace-p0-packs-payout-collusion-design.md`](./2026-08-07-marketplace-p0-packs-payout-collusion-design.md) (Implemented)

> **PRIVATE / INTERNAL ONLY — ratings & gradings.**  
> Policy: [`docs/compliance/RATING_PRIVACY.md`](../../compliance/RATING_PRIVACY.md).

## Goal

Close Important gaps left after Marketplace P0 so pre-payout control matches the written P0 contract: hold ≠ delay, webhooks on create/release, no SHA-synthetic mule seeding in production list paths, hardened S2S auth, honest release errors, and bridge failure metrics.

## Non-negotiables

- No stubs or demo-as-source-of-truth. Durable `marketplace_payout_holds` remains authoritative.
- Do **not** re-home loyalty-abuse engines into Tarka (Track B owns optional HTTP adapter later).
- Do **not** forge LIVE partner pins (Track C owns live fusion proof later).
- Ratings/grades stay private.
- Fail-soft: webhook delivery failure must not roll back hold create/release; bridge failure must not fail evaluate.

## Out of scope (later tracks)

| Track | Scope |
| --- | --- |
| B | COD/offline-payment pack; decision-api → loyalty-abuse redeem HTTP adapter |
| C | Live Fingerprint/Incognia partner-fusion tenant proof + evidence SHA |

## Architecture

```
evaluate (decision-api)
  checkpoint = metadata.checkpoint==payout OR event_type==payout
  tags ∩ {action:payout_hold, action:payout_delay}
  → BackgroundTasks → POST /v1/internal/marketplace/payout-holds
       status: held | pending (from tags)
       hold_duration: 72h hold | delay_hours (default 24) for delay
  → upsert durable row
  → record + deliver marketplace webhook (payout_hold) if callback configured

GET /v1/marketplace/payout-delay
  → list durable holds only
  → mule automation: upsert ONLY from real candidates (graph/feed), never SHA seed
  → source: durable | durable+automation

release
  → release_hold → 404 if missing
  → webhook payout_release if configured
```

## Slice A1 — Hold vs delay semantics

### Tag → status / duration

| Tag present | `status` | Duration source |
| --- | --- | --- |
| `action:payout_hold` (alone or with delay) | `held` | `hold_duration_hours_default` (existing, default 72) |
| `action:payout_delay` only | `pending` | `delay_hours_for_action_payout_delay` (new, default 24) |

If both tags fire, **hold wins** (`held` + hold duration).

### Checkpoint

`should_create_payout_hold` returns true when:

1. Tags intersect `{action:payout_hold, action:payout_delay}`, AND  
2. `metadata.checkpoint == "payout"` **OR** `event_type == "payout"` (pass `event_type` into the helper / from-evaluate entry).

### Config (payout-delay config blob)

Add / honor:

- `delay_hours_for_action_payout_delay` (int, default 24, clamped e.g. 1–168)
- `honor_evaluate_action_tags` (bool, default `true`) — when false, bridge skips create (internal mule/analyst paths still work)
- Keep existing: `automation_enabled`, `mule_score_hold_threshold`, `hold_duration_hours_default`

Bridge reads ingress defaults for duration when building payload, or encodes hours in create body; prefer create body fields `status`, `hold_duration_hours` set by decision-api from settings mirrored or constants matching guide.

**Decision:** decision-api owns tag→status mapping; sends `status` + `hold_duration_hours` on internal create. Ingress config supplies defaults for mule path and for PATCH config UI.

## Slice A2 — Webhooks

Reuse `marketplace_webhook_logs` record/deliver helpers.

| Event | Signal string | When |
| --- | --- | --- |
| Hold/delay created | `payout_hold` | After upsert that **inserts** a row or changes status into `held`/`pending` (internal create + mule sync). Skip webhook on no-op refresh of identical held row. |
| Released | `payout_release` | After successful `release_hold` that actually released a row |

Payload includes at least: `tenant_id`, `payout_id`, `entity_id`, `status`, `hold_reason`, `trace_id`, `decision_id` if present.

Callback URL: same tenant marketplace webhook callback resolution as existing block dispatch (reuse lookup; if none configured, skip deliver silently after optional record-skip).

Extend signal typing beyond `block` if currently Literal-constrained — allow `payout_hold` / `payout_release` without breaking block path.

Webhook errors: log + leave hold/release transaction committed.

## Slice A3 — Mule automation without SHA seed

### Remove

- `_mule_score_candidate` SHA256 synthetic generator from production list/sync path.
- Any loop that invents `payout_*` ids from tenant hash on GET list.

### Keep / add

1. **Explicit candidates only:** `sync_mule_holds_from_candidates(session, tenant_id, cfg, candidates: list[dict])` where each candidate **must** include `payout_id`, `entity_id`, `mule_score` (optional amount/currency). Used by tests and by config/ingest.
2. **List path:** GET payout-delay calls sync **only** if `automation_enabled` and `cfg["mule_candidates"]` is a non-empty list (tenant config PATCH may set it for demos; production leave empty). **Never** invent `payout_id`s from hashes or entity ids alone.
3. **Optional graph enrich (same PR if cheap):** when `GRAPH_SERVICE_URL` is set, for each candidate with `payout_id` + `entity_id`, overwrite `mule_score` from graph vertex property if present; skip candidate if graph errors (do not invent rows).
4. **Default `automation_enabled`:** `false`. List → durable holds, `source: "durable"`. When sync writes ≥1 row from real candidates, `source: "durable+automation"`.

Tests that previously relied on SHA seed must PATCH `mule_candidates` or call the sync helper directly.

## Slice A4 — Auth + release honesty

1. Compare internal token with `secrets.compare_digest` (constant-time).
2. Tests:
   - missing `X-Internal-Token` → 401 when token configured
   - wrong token → 401
   - valid token without API key → 201 (existing)
3. `release` HTTP handler: if `release_hold` returns `None`, respond **404** (no synthetic `{status: released}` success).
4. Startup / readiness: warn (log) when `INGRESS_INTERNAL_TOKEN` is empty — do not crash local/dev.

## Slice A5 — Bridge observability

On bridge POST failure (after should_create true): keep `log.exception`; also increment existing decision-api metrics helper (`metrics_inc("payout_hold_bridge_failed")` or service-consistent counter name).

Gate enqueue remains at outcome scheduler via `should_create_payout_hold`.

## Files (expected)

| File | Change |
| --- | --- |
| `decision_api/payout_hold_bridge.py` | checkpoint via event_type; status/duration; metric |
| `decision_api/decision_outcome.py` | pass event_type into bridge |
| `decision_api/tests/test_payout_hold_from_evaluate.py` | delay/pending, event_type, metric |
| `integration_ingress/payout_delay_automation.py` | remove SHA seed; candidate sync; config keys; release None |
| `integration_ingress/main.py` | webhook after create/release; 404 release; config fields |
| `integration_ingress/marketplace_webhook_logs.py` | signal literals |
| `integration_ingress/payout_hold_store.py` | if needed for pending |
| `integration_ingress/tests/test_payout_delay_durable.py` | auth negative, webhook, no SHA pollution |
| `docs/docs/guides/vertical-packs-marketplace-delivery.md` | delay vs hold, webhooks, mule |

## Acceptance

1. Evaluate with `action:payout_delay` + payout checkpoint → durable row `status=pending`, duration ≈ delay hours.  
2. Evaluate with `action:payout_hold` → `status=held`.  
3. Internal create with callback configured → webhook log `payout_hold`.  
4. Release existing → webhook `payout_release`; release missing → 404.  
5. GET payout-delay with automation on and **no** candidates → no new synthetic payout ids.  
6. Wrong/missing internal token → 401.  
7. Bridge failure increments metric and evaluate still 200.  
8. Guide documents A1–A3 behavior.

## Program context

After P1: **Track B** (COD pack + loyalty-abuse redeem adapter), then **Track C** (live partner-fusion proof).
