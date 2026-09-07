# Clone-and-run desk

**Goal:** From a clean checkout, one command starts Lite + fraud-desk and POSTs a few real evaluate events so `/decisions` has receipts.

Tarka application code is **source-available** under Elastic License 2.0 (not open-source). Self-hosting on your own metal or VPC for your own operations is allowed; providing Tarka to third parties as a hosted or managed service is not.

## Command

```bash
make doctor && make demo
```

`make demo` is the **demo** skin (first-hour pages). `make product` is the **product** skin: same APIs, plus visual builder, backtest, entity lists, simulation, and analytics, with `infra/deploy/desk_provision.example.json` mounted. Product is not Command Center or sales-only pitch pages. Optional sales-only overlay still uses `VITE_DESK_PROFILE=brochure` / `VITE_LEAN_NAV=false`. Leftover switches (`flag_mints_leftover`, claim, QA isolate, receipt brief) live in that file or `TARKA_*`. Auto-Promote is **off** and is not a shipped unattended path.

`make doctor` checks Docker Desktop (Compose v2), ports `8000` `8001` `3000` `5432` `6379`, and ~4 GB RAM. Each fail names the fix. Then `make demo` starts Lite + fraud-desk and runs the receipt walk.

Same script: `bash scripts/oss/up_desk.sh`. First build is the long pole.

Mac and Linux: Docker Desktop or Docker Engine + Compose v2. On a laptop, stop local Postgres/Redis if those ports are busy.

Health for evaluate is **`GET http://127.0.0.1:8000/decisions/v1/health`**. A process on `:8000` without that path is not a healthy Tarka stack.

## Failure modes

| Symptom | What it is | Fix |
|---------|------------|-----|
| `make doctor` fail on `5432` / `6379` | Host Postgres/Redis (or leftover containers) own the ports. Not Tarka evaluate. | Stop the host service or `docker compose -f infra/deploy/docker-compose.lite.yml down -v`. Re-run `make doctor`. |
| `8000` up, `GET /decisions/v1/health` fails | Stale lite / other process. No `/decisions` routes. | Same `down -v`, then `make doctor && make demo`. Do not treat the old container as healthy. |
| `8000` already serves `/decisions/v1/health` | A Tarka evaluate is already up. | `make demo` skips the compose wait. For a clean rebuild: `down -v` first. |
| Health timeout after compose | Image or volume from an old lite. | Rebuild: `docker compose -f infra/deploy/docker-compose.lite.yml -f infra/deploy/docker-compose.fraud-desk.yml up -d --build`. |

If Docker is not available, doctor exits with that message. The walk logic is still CI-safe:

```bash
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_walk_receipts.py
PYTHONPATH=scripts/oss python3 infra/scripts/ci/test_sdk_walk.py
```

## What it does

1. `make doctor` (also run from `up_desk.sh` if evaluate is not already healthy). Copies `infra/deploy/env/community.env.example` to `infra/deploy/.env` when missing (local `ALLOW_INSECURE_NO_AUTH=true`).
2. Optional TTY prompt for a BYO LLM URL / key / model. Enter skips. Values go in `infra/deploy/.env` only (not the browser). `make demo` never starts `shadow_agent`. `make product` starts it only when `OPENAI_BASE_URL` is set.
3. `docker compose` lite + fraud-desk. If health never comes up (3 min), the script stops and does **not** run the walk.
4. `python3 scripts/oss/walk_receipts.py` — three evaluate POSTs against **shipped** packs (`default.json`, `device_signals.json`, `vertical_payment_risk_v1.json`). Decisions are whatever evaluate returns. The walk does not invent ALLOW / REVIEW / DENY.

On those packs alone (base 10, review 50, deny 80) the three payloads score 10 / 75 / 90 → allow / review / deny. Live evaluate may add hop or degrade tags — believe the receipt. There is no consortium SKU on this walk.

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
- Empty `GRAPH_SERVICE_URL` turns hops off (evaluate-only fallback) — **not sibling identity**. Lite compose sets the AGE graph URL. Hunt chrome is the same path: empty `VITE_GRAPH_SERVICE_URL` **or** `VITE_HUNT_ENABLED=0` (`TARKA_HUNT_ENABLED=0` / `hunt.enabled: false` on `make product`). File-only Hunt-off does not hide the baked desk until rebuild.
- Hop packs (`USES_DEVICE` …) stay `mode=shadow`. Beachhead Observe seeds (promo / COD / payout) stay Observe. Live FLAG only after human Promote.
- An edge is real only when the receipt wrote it. This walk does not mock a hop SKU. Not GNN live.

If every receipt is ALLOW, that is an honest pack outcome on this desk, not a failed demo. The receipt why and Hunt person (`entity_id`) still stand.

## Deeper path

Step-by-step compose, curl, and troubleshooting: [15-minute first decision](./oss-15-minute-first-decision.md) (`python3 scripts/oss/first_decision_smoke.py`). Optional SDK path (same three cases via `DecisionClient`, desk already up): `make sdk-walk` — not a second Day-1 promise.
