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
| `emit_only` | Advisory. Also listed on `receipt.suggested_actions[]` with parallel `action_ids`. | Pack-why always present. |
| `handoff` | Authoritative for that tenant. | Pack-why always present. Same mapping may appear on `suggested_actions[]` with parallel `action_ids`. |

Product copy must not claim “we blocked” in `emit_only`.

## Webhooks

Empty URL = that plane off. When a secret is set (`TARKA_ENFORCEMENT_WEBHOOK_SECRET` or provision `secret_env`), POSTs include `x-tarka-signature` = hex HMAC-SHA256 of the raw body. No secret = no signature header (not the contract default for a live sink).

`suggested_actions[]` stays a `list[str]` token list (`deny`, `review`, `flag`, `hold_payout`, `deny_promo`, `suspend_courier`, `step_up`). Parallel `action_ids` maps each token to an idempotent `action_id`. The delivery also carries `action_id` (first suggested token’s id, or the empty-token hash when the list is empty).

**`action_id` scheme** (`tarka.action_id/v1`): hex SHA-256 of UTF-8 lines `tarka.action_id/v1`, `tenant_id`, `trace_id`, action token, pack hash. Pack hash is evaluate `policy_set_id` (stable pack identity) or empty when unknown. Same tuple → same id on webhook retries. Different trace or action token → different id. Not a random UUID per POST. Buyer product sinks dedupe on `action_id`. Retry/DLQ is D9.

| Event | When |
|-------|------|
| `decision.emitted` | Always (both modes). |
| `decision.enforced` | Handoff only. Name is the contract intent; runtime lands in W8. |

## Who consumes

Buyer payment / promo / courier systems subscribe to webhooks or read `suggested_actions[]`. Tarka does not host those services.

## Product ACK

Inbound `POST /v1/enforcement/acks` records buyer delivery/application status bound to the evaluate/audit `trace_id` and the G4.2 `action_id`. Fields: `trace_id`, `action_id`, `status`, `ts`, `actor` (tenant_id). Query `GET /v1/enforcement/acks?trace_id=&tenant_id=&action_id=`. Unknown `trace_id` is a structured 4xx (not a silent 200). Malformed `action_id` is a structured 4xx.

When `TARKA_ENFORCEMENT_WEBHOOK_SECRET` is set, POST must carry `x-tarka-signature` = hex HMAC-SHA256 of the raw body (same brand as outbound enforcement webhooks).

ACK is not Promote, Confirm, or Demote and does not change pack lifecycle. Not a case CRM. Desk delivery-status glass is G4.4.

## Out of scope

- Implementing every vocabulary action as Tarka-owned side effects
- Case CRM
- Silent block / hold / deny in `emit_only`
- Day-1 default of `handoff`
- Desk delivery status glass (G4.4)
- Treating ACK as Promote/Demote
- D9 retry + DLQ
