# Queue seam v1

Connectors only. **Tarka is not a case CRM.** Leftovers + Hunt stay residual.

## Empty URL = off

`QUEUE_WEBHOOK_URL` unset or empty → no outbound POST (same pattern as `GRAPH_SERVICE_URL`).

Optional: `QUEUE_WEBHOOK_SECRET` (HMAC hex in `x-tarka-signature`), `QUEUE_SEAM_MODE=webhook|issue_tracker`, `ISSUE_TRACKER_AUTH_HEADER`, `DESK_PUBLIC_BASE_URL`.

## Choke point

One emit after leftover-eligible evaluate decisions (`deny` / `review` / `FLAG` when FLAG mints leftover) in `schedule_decision_outcomes`. Webhook 500s never fail evaluate or leftover mint.

## Outbound `queue.upsert` (`tarka.queue_upsert/v1`)

`tenant_id`, `leftover_id` (or `flag_id`), `trace_id`, `evaluation_token`, `entity_id`, `action`, `enforcement_mode`, `pack_why_summary`, `deep_link`, `emitted_at`.

`action` is advisory unless enforcement mode is `handoff`. This contract does not invent enforcement.

## Inbound disposition → label

Reuse `POST /v1/webhooks/disposition` → `bind_late_label`. Explicit `label_kind` wins.

| disposition_code | label_kind |
|------------------|------------|
| confirmed_fraud | fraud |
| false_positive | fp |
| promo_abuse | promo_abuse |
| chargeback_lost | chargeback |
| collusion | collusion |
| unknown | reject (`reason_code=unknown_disposition`) |

Override map via `QUEUE_DISPOSITION_MAP_JSON`.

## Issue-tracker mode

Same choke point. `QUEUE_SEAM_MODE=issue_tracker` wraps the upsert in `{title, body, queue_upsert}`. Chat/Slack notify is **not** a queue.

## Out of scope

Branded SaaS SDKs, Tarka-hosted ticket DB, sync blocking evaluate, bidirectional field sync, SLA ticket routing as a product.
