# Enforcement contract v1

Single source of truth for **emit-only vs handoff**. Runtime `enforcement.mode` is implemented in W8; this contract is the buyer-facing rule.

## Default

`enforcement.mode = emit_only`

Evaluate always returns a pack-why receipt. Buyers treat the HTTP `action` as **advisory** unless they have handed Tarka enforcement.

## Handoff

`enforcement.mode = handoff` only when the **buyer contract / tenant integration** explicitly hands Tarka enforcement. Handoff is never the Day-1 or compose default.

In handoff, the sync evaluate HTTP `action` is **authoritative** for that tenant. Tarka still does not implement the buyer’s payment, promo, or courier systems.

## Vocabulary (extensible)

| Token | Meaning |
|-------|---------|
| `emit_only` | Mode: emit decision + receipt + webhooks. No silent block. |
| `handoff` | Mode: buyer has contracted Tarka to enforce the action. |
| `allow` | Suggested / (handoff) applied allow |
| `review` | Suggested / (handoff) applied review |
| `deny` | Suggested / (handoff) applied deny |
| `flag` | Suggested / (handoff) applied flag |
| `step_up` | Suggested / (handoff) applied step-up |
| `hold_payout` | Suggested action for buyer payout systems |
| `deny_promo` | Suggested action for buyer promo systems |
| `suspend_courier` | Suggested action for buyer courier systems |

Tarka does not implement payout holds, promo denial, or courier suspension services.

## Sync evaluate HTTP

| Mode | HTTP `action` | Receipt |
|------|----------------|---------|
| `emit_only` | Advisory. Also listed on `receipt.suggested_actions[]`. | Pack-why always present. |
| `handoff` | Authoritative for that tenant. | Pack-why always present. Same mapping may appear on `suggested_actions[]`. |

Product copy must not claim “we blocked” in `emit_only`.

## Webhooks

| Event | When |
|-------|------|
| `decision.emitted` | Always (both modes). |
| `decision.enforced` | Handoff only. Name is the contract intent; runtime lands in W8. |

## Who consumes

Buyer payment / promo / courier systems subscribe to webhooks or read `suggested_actions[]`. Tarka does not host those services.

## Out of scope

- Implementing every vocabulary action as Tarka-owned side effects
- Case CRM
- Silent block / hold / deny in `emit_only`
- Day-1 default of `handoff`
