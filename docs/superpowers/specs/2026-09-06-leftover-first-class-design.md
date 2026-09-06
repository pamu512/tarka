# First-class leftover (P-left1)

**Date:** 2026-09-06  
**Status:** Design locked in chat (`go`).  
**Branch:** `honesty/leftover-first-class` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** `case_api/leftover.py`, `GET /v1/leftovers`, `decision_outcome.py`, Leftovers desk

## Goal

Leftover API story without `case_id`. Case row stays the store. FLAG mint, multi-claim, QA isolate, and receipt brief are env-gated and default off.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote.
- No `desk_provision.json`. Four env stubs only.
- `leftover_id` = case row id. Drop `case_id` from leftover JSON.
- Case `/v1/cases/…` and act `case_id` stay (not the leftover story).
- Demo ≠ product. No named third-party desks. Do not call Tarka OSS.

## Env (default off)

| Env | On |
|-----|----|
| `TARKA_FLAG_MINTS_LEFTOVER` | evaluate `flag` may mint a leftover (deny/review unchanged) |
| `TARKA_MULTI_ANALYST_CLAIM` | second analyst may claim (overwrites) |
| `TARKA_QA_QUEUE_ISOLATES` | `qa:pending` rows leave `GET /v1/leftovers` |
| `TARKA_RECEIPT_BRIEF` | leftover JSON may include `receipt_brief` |

## Testing

- leftover_row has `leftover_id`, no `case_id`; no `receipt_brief` unless env on.
- FLAG does not mint unless env on.
- Second claim 409 unless multi-claim env on.
- QA-pending leftover hidden from list when isolate on.
- Leftovers desk claims via `leftover_id`.

## Success

Named desk can enable FLAG mint + claim. Default stays thin.

## Non-goals

- New leftover table. P-day1 provision file. QA store rebuild.
