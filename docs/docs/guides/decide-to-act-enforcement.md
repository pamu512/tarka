# Decide → act (platform enforcement)

After evaluate, Tarka exposes a **platform protect verb** so the calling stack can act without inventing MFA providers inside Tarka.

## Sync response

`POST /v1/decisions/evaluate` includes:

| Field | Values | Meaning |
|-------|--------|---------|
| `decision` | `allow` / `review` / `deny` | Risk decision |
| `recommended_action` | e.g. `block`, `step_up_mfa`, `manual_review` | Policy hint |
| `enforcement_action` | `allow` \| `step_up` \| `block` | **Act verb** — what the platform should do |
| `score` | number | The one risk score. There is no `friction_tier`. |

Mapping (also used by async webhooks):

- `decision=deny` → `block` (always)
- else if `recommended_action` is step-up/challenge class → `step_up`
- else → `allow`

Audit `payload_snapshot` and decision-log records include the same `enforcement_action`.

## Async webhooks

| Env / provision | Schema | When |
|-----------------|--------|------|
| `TARKA_ENFORCEMENT_WEBHOOK_URL` or `hooks.enforcement.url` (+ secret via `TARKA_ENFORCEMENT_WEBHOOK_SECRET` or `secret_env`) | `tarka.enforcement/v1` | Every evaluate that **reached** Tarka, including allow. No evaluate = no webhook. |
| `TARKA_CHALLENGE_WEBHOOK_URL` (+ optional secret) | `tarka.challenge_webhook/v1` | Step-up class `recommended_action` only |
| `TARKA_OBSERVE_NOTIFY_WEBHOOK_URL` or `hooks.observe_notify.url` | `tarka.observe_notify/v1` | Observe inbox events (not evaluate) |

Empty URL = that sink off. Slack/email: point the URL at their incoming webhook — Tarka does not ship a first-party mailer.

Product observe inbox (`profile=product` or `TARKA_OBSERVE_NOTIFY_STORE=postgres`) is a Postgres table. Demo keeps `observe_notify.jsonl`. Env store wins.

Signature header: `x-tarka-signature` = hex HMAC-SHA256 of the raw body when secret is set.

Inbound product ACK: `POST /v1/enforcement/acks` (same signature header when the enforcement secret is set). Query `GET /v1/enforcement/acks?trace_id=&tenant_id=`. Unknown trace is 4xx. ACK is not Promote/Demote. Delivery journal query: `GET /v1/enforcement/deliveries?trace_id=&tenant_id=&action_id=&status=` (tenant-scoped; unknown trace → empty `deliveries[]`). Journal HTTP 2xx ≠ product ACK. Desk `/decisions/:id` (G4.4 strip, D9.4) shows emitted / retrying / dead_lettered / acked / not configured. Residual `failed` only for unclassified journal error. Empty URL = not configured. Delivery reliability ≠ enforcement SKU suite.

Headers: `x-tarka-enforcement-event` (`allow`/`step_up`/`block`) or `x-tarka-challenge-event` (`step_up`).

## Local demo

```bash
# Terminal A — mock tenant receiver
python3 scripts/oss/enforcement_webhook_mock.py --port 8765

# Point decision-api at the mock (compose/.env), then:
export TARKA_ENFORCEMENT_WEBHOOK_URL=http://host.docker.internal:8765/enforcement
# restart decision-api

python3 scripts/oss/decide_to_act_smoke.py
```

Ops: `GET /v1/ops/governance` → `integrity_ingress.enforcement_webhook_configured` (UI: `/ops/integrity`).

## Out of scope

SMS / email / WebAuthn providers — tenant owns challenge UX; Tarka fires signed intent.
