# Downstream Contracts (Private)

> INTERNAL — host supplies fields; Tarka does not call carriers/card networks.

## Chargeback early alert → dispute

1. Gateway POSTs consortium payload to `POST /v1/webhooks/chargeback-alert/{provider}`.
2. Response includes `features`, `dispute_hint` (evidence booleans + `evidence_pdf_urls`), optional `dispute_bridge.dispute_id`.
3. Host re-evaluates with `dispute_hint.evaluate_reprocess` as evaluate `metadata` (feeds `dispute_evidence` into representment depth).

## FTID / POD / COD

- `metadata.ftid.*` — Downstream warehouse intake booleans.
- `metadata.pod.*` — OTP / geofence / photo hash flags.
- `metadata.cod.*` — refusal rate, address jig/hop, selective theft.

## Sibling bridges

- Loyalty / refund / cancel: fail-soft when URL unset (`GET /v1/ops/sibling-bridge-posture`).
- Refund effects are advisory unless host-action opted in.
