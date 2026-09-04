# OSS 15-minute path — first decision

**Goal:** From a clean checkout, get a live evaluate response (and optional UI) in about 15 minutes using **Tarka Lite**.

The one-command front door is [`make demo`](./clone-demo.md). This page is the longer compose / curl / smoke path.

Self-hosting Tarka on your own metal or VPC for your own operations is allowed under Elastic License 2.0; providing Tarka to third parties as a hosted or managed service is not.

## Prerequisites

- Docker + Docker Compose v2
- ~4 GB RAM free for lite images (evaluate + AGE + graph-service; see [SRE Compose profiles](../operations/sre-compose-profiles.md))
- Ports free: `8000`, `8001`, `3000`, `5432`, `6379`

## Steps

One command (desk + receipt walk — same as `make demo`):

```bash
bash scripts/oss/up_desk.sh
```


### 1. Start Lite (≈5–10 min first build)

```bash
cd /path/to/tarka
cp infra/deploy/env/community.env.example infra/deploy/.env
# Local try-it: allow unauthenticated evaluate (never use in production)
echo 'ALLOW_INSECURE_NO_AUTH=true' >> infra/deploy/.env

# Lite = evaluate + AGE graph (+ optional fraud-desk overlay for lean nav + desk-strict)
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  --env-file infra/deploy/.env up -d --build
```

Wait until healthy:

```bash
curl -sf http://127.0.0.1:8000/decisions/v1/health >/dev/null && echo ok
```

### 2. First decision (smoke)

```bash
python3 scripts/oss/first_decision_smoke.py
```

Expect exit **0** and a printed `trace_id` + `decision` / `score`.

Manual equivalent (core-api mounts decision-api at `/decisions`):

```bash
curl -sS -X POST 'http://127.0.0.1:8000/decisions/v1/decisions/evaluate' \
  -H 'content-type: application/json' \
  -d '{
    "tenant_id": "demo",
    "event_type": "payment",
    "entity_id": "oss-user-1",
    "payload": {"amount": 42.0, "currency": "USD", "channel": "card_not_present"}
  }' | jq '{trace_id, decision, score}'
```

### 3. UI (optional)

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) — first paint is `/graph` (Hunt) when graph is on. Receipts stay at `/decisions`. Residual cases are not the home. The Person evaluate wrote should be on Hunt.

## Next after first decision

| Topic | Guide |
|-------|--------|
| Leftovers + Hunt | [Feature data flows §3](./feature-data-flows.md#3-leftovers-hunt-brief-sar) |
| Observe / promote | [shadow-and-ab-testing.md](./shadow-and-ab-testing.md) |
| Community vs Pro profiles | [deployment-profiles-community-vs-pro.md](./deployment.md) |
| Production hardening | `infra/deploy/docker-compose.production-hardening.yml` + [tls-pinning-and-signed-requests.md](./tls-pinning-and-signed-requests.md) |
| Counter replay parity | [counter-replay-parity.md](./counter-replay-parity.md) |
| Demo vertical (evaluate + case + ingest) | `infra/scripts/ci/demo_vertical_smoke.py` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `401` / auth on evaluate | Ensure `ALLOW_INSECURE_NO_AUTH=true` in `infra/deploy/.env` and recreate `core-api` |
| Health not ready | `docker compose -f infra/deploy/docker-compose.lite.yml ps` — wait for postgres/redis/core-api healthy |
| Port conflict | Stop local postgres/redis or change published ports in compose |
