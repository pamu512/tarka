# Decide → act (platform enforcement)

After evaluate, Tarka exposes a **platform protect verb** so the calling stack can act without inventing MFA providers inside Tarka.

## Sync response

`POST /v1/decisions/evaluate` includes:

| Field | Values | Meaning |
|-------|--------|---------|
| `decision` | `allow` / `review` / `deny` | Risk decision |
| `recommended_action` | e.g. `block`, `step_up_mfa`, `manual_review` | Policy hint |
| `enforcement_action` | `allow` \| `step_up` \| `block` | **What the platform should do** |

Mapping (also used by async webhooks):

- `decision=deny` → `block` (always)
- else if `recommended_action` is step-up/challenge class → `step_up`
- else → `allow`

Audit `payload_snapshot` and decision-log records include the same `enforcement_action`.

## Async webhooks

| Env | Schema | When |
|-----|--------|------|
| `TARKA_ENFORCEMENT_WEBHOOK_URL` (+ optional `TARKA_ENFORCEMENT_WEBHOOK_SECRET`) | `tarka.enforcement/v1` | Every evaluate outcome (background) |
| `TARKA_CHALLENGE_WEBHOOK_URL` (+ optional secret) | `tarka.challenge_webhook/v1` | Step-up class `recommended_action` only |

Signature header: `x-tarka-signature` = hex HMAC-SHA256 of the raw body when secret is set.

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
