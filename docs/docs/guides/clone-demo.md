# Clone-and-run desk

**Goal:** From a clean checkout, one command starts Lite + fraud-desk and POSTs a few real evaluate events so `/decisions` has receipts.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). Self-hosting on your own metal or VPC for your own operations is allowed; providing Tarka to third parties as a hosted or managed service is not.

## Command

```bash
make doctor && make demo
```

`make doctor` checks Docker Desktop (Compose v2), ports `8000` `8001` `3000` `5432` `6379`, and ~4 GB RAM. Each fail names the fix. Then `make demo` starts Lite + fraud-desk and runs the receipt walk.

Same script: `bash scripts/oss/up_desk.sh`. First build is the long pole.

Mac and Linux: Docker Desktop or Docker Engine + Compose v2. On a laptop, stop local Postgres/Redis if those ports are busy.

If Docker is not available, doctor exits with that message. The walk logic is still CI-safe:

```bash
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py
```

## What it does

1. `make doctor` (also run from `up_desk.sh` if evaluate is not already healthy). Copies `infra/deploy/env/community.env.example` to `infra/deploy/.env` when missing (local `ALLOW_INSECURE_NO_AUTH=true`).
2. Optional TTY prompt for a BYO LLM URL / key / model. Enter skips. Values go in `infra/deploy/.env` only (not the browser). Shadow stays off on this compose until you add that service later.
3. `docker compose` lite + fraud-desk. If health never comes up (3 min), the script stops and does **not** run the walk.
4. `python3 scripts/oss/walk_receipts.py` — three evaluate POSTs against **shipped** packs (`default.json`, `device_signals.json`, `vertical_payment_risk_v1.json`). Decisions are whatever evaluate returns. The walk does not invent ALLOW / REVIEW / DENY.

On those packs alone (base 10, review 50, deny 80) the three payloads score 10 / 75 / 90 → allow / review / deny. Live evaluate may add graph, consortium, or degrade deltas — believe the receipt.

demo-burst (investor / SAR pitch, token-gated) is not this path.

## After it prints PASS

The last line before PASS is one click: `NEXT: http://127.0.0.1:3000/graph?entity_id=…` — open that. Other surfaces:

| Surface | URL |
|---------|-----|
| Hunt | `/graph` (home when graph is on) — look up the printed `entity_id` |
| Receipts | `/decisions` |
| Observe | `/ops/shadow` |
| Notifications | `/notifications` — ready to Promote and live-rule slip (same English as Observe) |

Optional outbound copy of those events: set `TARKA_OBSERVE_NOTIFY_WEBHOOK_URL` (and optional `TARKA_OBSERVE_NOTIFY_WEBHOOK_SECRET`) on decision-api. Envelope `tarka.observe_notify/v1`. Empty URL = desk only. Webhook 5xx does not block evaluate or Promote.

To add a BYO LLM after Day-1, put the same four vars in `infra/deploy/.env` (`SHADOW_LLM_BACKEND=vllm` or `self-hosted`, `SHADOW_LLM_BASE_URL`, `SHADOW_LLM_API_KEY`, `SHADOW_LLM_MODEL`) and start `shadow_agent` with that env. Do not put keys in the browser. Advise `OPENAI_BASE_URL` is a different overlay.

## What you're looking at

- Packs control the decision. These POSTs hit shipped JSON packs under `services/decision-api/rules/`; evaluate never invents ALLOW / REVIEW / DENY.
- Receipt why is `rule_hits` + `reasons` on the evaluate response and on desk `/decisions`.
- Observe on `/ops/shadow` is pack canary + leftover promote + live-rule slip — not live production traffic and not a model.
- Empty `GRAPH_SERVICE_URL` turns hops off (evaluate-only fallback). Lite compose sets the AGE graph URL.
- An edge is real only when the receipt wrote it. This walk does not mock a hop SKU.

If every receipt is ALLOW, that is an honest pack outcome on this desk, not a failed demo. The receipt why and Hunt person (`entity_id`) still stand.

## Deeper path

Step-by-step compose, curl, and troubleshooting: [15-minute first decision](./oss-15-minute-first-decision.md) (`python3 scripts/oss/first_decision_smoke.py`).
