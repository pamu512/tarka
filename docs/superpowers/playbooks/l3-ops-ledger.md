# L3 ops ledger — four-week live shadow clock

**Machine source of truth:** [`docs/compliance/l3-ops-ledger.json`](../../compliance/l3-ops-ledger.json)  
**API:** `GET /v1/ops/l3-ledger` · `POST /v1/ops/l3-ledger/arm` · `POST /v1/ops/l3-ledger/weeks/{n}/sign`  
**Host actions:** `POST /v1/ops/host-actions` (internal JSONL sink)  
**Playbook:** [2026-08-05-shadow-four-week-critical.md](./2026-08-05-shadow-four-week-critical.md)  
**Sim (not L3):** `scripts/oss/shadow_four_week_sim.py` → banner `NOT PRODUCTION L3` — **never writes the ledger**

## Honesty

Arming the ledger starts the **clock**, not the claim. `claim_allowed` is true only at status `COMPLETE` (four signed live weeks + Week-4 ECE on real labels). Demo/sim tenants and sim sinks are rejected.

## Clock

| Field | Value |
| --- | --- |
| Tenant id | _pending operator_ |
| Week 1 start (UTC date) | _not set_ |
| Week 4 end (UTC date) | _not set_ |
| Shadow evaluate enabled | no |
| Host action log sink | no |
| Label join / ECE on real labels | no |

## Week checklist (live only)

Copy rows into dated notes when a week completes. Do not check off from sim.

| Week | Shadow on | Host actions logged | Outcomes joined | Weekly metrics | ECE candidate | Sign-off |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 2 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 3 | ☐ | ☐ | ☐ | ☐ | — | ☐ |
| 4 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |

## How to start the clock (operator)

**UI (preferred):** Ops → Shadow (`/ops/shadow`) → **Arm L3 clock** with a named live tenant + host action sink (defaults to `internal_host_action_sink`). Then log host actions and **Sign week** N after each live week. Week 4 requires the ECE checkbox.

```bash
# API equivalent
curl -X POST "$DECISION_API_URL/v1/ops/l3-ledger/arm" -H "Authorization: …" -H "Content-Type: application/json" -d '{
  "tenant_id": "YOUR_LIVE_TENANT",
  "week1_start_utc": "2026-08-07",
  "host_action_sink": "internal:jsonl:…",
  "shadow_evaluate_enabled": true,
  "actor": "you"
}'
curl -X POST "$DECISION_API_URL/v1/ops/host-actions" -d '{"tenant_id":"YOUR_LIVE_TENANT","action":"challenge_issued","trace_id":"…"}'
# Sign weeks 1–4; week 4 requires ece_candidate=true + real-label ECE
```

Rejects: `demo` / `fixture` / `sim` tenants; sinks containing `shadow_four_week_sim`.

## Status

Committed ledger starts **NOT_STARTED**. Claim lock stays closed for L3 (C5) until `COMPLETE`.
