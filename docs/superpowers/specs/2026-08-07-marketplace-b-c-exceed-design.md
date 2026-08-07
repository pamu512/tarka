# Marketplace Tracks B+C — Close gaps / exceed market

**Date:** 2026-08-07  
**Status:** Implemented (2026-08-07)  
**Base:** `master` post P1 (`92bc2595`)

> **PRIVATE / INTERNAL ONLY — ratings & gradings.**  
> Policy: [`docs/compliance/RATING_PRIVACY.md`](../../compliance/RATING_PRIVACY.md).

## Goal

Ship Track B + C and remaining marketplace demo gaps so Tarka exceeds brochure-only competitors on COD abuse, redeem-time loyalty orchestration, durable promo/seller boards, and honest partner-fusion proof posture.

## Non-negotiables

- No loyalty-abuse multi-gate re-home; HTTP `POST /v1/evaluate` with `type=redeem` only.
- No forged LIVE partner pins; L2 stays WAIVED without real vendor credentials.
- No stubs as source of truth for promo/seller boards.
- Fail-soft: external HTTP failures never fail evaluate.

## Track B1 — COD / offline pack

- Pack id: `offline_payment` (≥5 rules).
- Features (from payload/metadata into evaluate features): `payment_method`, `is_cod`, `is_offline_payment`.
- Tags: `vertical:offline_payment`, `risk:cod_abuse`, `risk:address_hop`, `action:payout_hold` / review tags.
- Kill criteria + list/install tests like marketplace packs.

## Track B2 — Loyalty-abuse redeem bridge

- Module `loyalty_abuse_bridge.py` (mirror payout_hold_bridge).
- Trigger: `metadata.checkpoint=redeem` OR `event_type=redeem`.
- `POST {LOYALTY_ABUSE_URL}/v1/evaluate` with EventEnvelope `type=redeem`, Bearer `LOYALTY_ABUSE_API_KEY`.
- Map friction → tags (`loyalty:friction:*`) + optional score bump evidence in response metadata; fail-soft + metric `loyalty_abuse_bridge_failed`.
- Config: `loyalty_abuse_url`, `loyalty_abuse_api_key`.

## Track B3 — Durable promo + seller boards

- Replace SHA demo generators as sole list content for promo-abuse and seller-integrity.
- Durable tables + stores + internal record endpoints; list `source=durable`.
- Empty tenant → empty list (not synthetic).

## Track C — Partner fusion proof

- Re-run fixture proof; refresh L1 SHA if needed.
- Attempt live; if no credentials, keep `partner-fusion-proof.live.status` as WAIVED with honest reason (do not forge LIVE).

## Out of scope

- GrabDefence SDK, chargeback guarantee product, live loyalty warehouse DB.
