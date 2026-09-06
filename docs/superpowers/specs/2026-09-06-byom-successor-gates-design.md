# BYO successor suggest after gates (P-obs2)

**Date:** 2026-09-06  
**Status:** Design locked in chat (`go`).  
**Branch:** `honesty/byom-successor-gates` stacked on P-reg1 (`#378` / `feat/desk-demo-vs-product`)  
**Related:** `POST /v1/rules/scout-pack`, `live_rule_slip.py`, Observe ease panel

## Goal

Host slip still parks `slip_critic` drafts and pings Observe. BYO may suggest a successor Observe draft only when `TARKA_BYO_SUCCESSOR_SUGGEST` is on. Without that env, BYO cannot author a slip successor. Model never demotes or Promotes live.

## Locked choices

- Evaluate stays Rust. Model never ALLOW / DENY / REVIEW / Promote / demote live.
- No `desk_provision.json`. Gate is env only.
- Empty plane URL = that plane off.
- Demo ≠ product. No named third-party desks. Do not call Tarka OSS.
- Reuse `POST /v1/rules/scout-pack`. No new endpoint.
- `409 slip_draft_exists` stays: `slip_successor_*` / `slip_retire_*` names, or a `live_rule_id` that already has a host slip slot.
- Scout `authored_by` is never `slip_critic`.

## Gate

`TARKA_BYO_SUCCESSOR_SUGGEST` — default off. Truthy: `1` / `true` / `yes` / `on`.

Successor-shaped scout body (after the 409 check): `evidence.slip_kind` is `successor` or `retire`. Env off → **403** `byo_successor_suggest_off`. Env on → shadow only (existing `mode=shadow` rule).

`authored_by=slip_critic` on scout-pack is rewritten to `scout_coordinated_burst`.

Host `maybe_park_live_rule_slip` + `observe_notify` pings unchanged.

## Desk copy

Successor lines: model suggested successor — human owns Promote. AI drafts stay distinct from `slip_critic`.

## Testing

- Helper: kind `successor` is shaped; plain scout name is not.
- Env off + `evidence.slip_kind=successor` → 403.
- Env on + legal field + leftover green → 201 shadow, `authored_by != slip_critic`.
- `name=slip_retire_r1` still 409 (no env).
- Host park + notify tests still pass.

## Success

Without the env, BYO cannot author a slip successor. With it, the write is Observe-only.

## Non-goals

- New successor endpoint. Publisher-only gate. P-left1 / P-day1. Auto-promote on.
