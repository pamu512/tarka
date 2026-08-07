# OSS 15-minute path — first decision

**Goal:** From a clean checkout, get a live evaluate response (and optional UI) in about 15 minutes using **Tarka Lite**.

## Prerequisites

- Docker + Docker Compose v2
- ~8 GB RAM free for images
- Ports free: `8000`, `3000`, `5432`, `6379`

## Steps

### 1. Start Lite (≈5–10 min first build)

```bash
cd /path/to/tarka
cp infra/deploy/env/community.env.example infra/deploy/.env
# Local try-it: allow unauthenticated evaluate (never use in production)
echo 'ALLOW_INSECURE_NO_AUTH=true' >> infra/deploy/.env

# Preferred: fraud-desk overlay (lean nav + desk-strict, no graph profile)
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

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) — Cases / audit should reflect the evaluate when the stack is wired (Lite frontend → core-api).

## Next after first decision

| Topic | Guide |
|-------|--------|
| Community vs Pro profiles | [deployment-profiles-community-vs-pro.md](./deployment-profiles-community-vs-pro.md) |
| Production hardening | `infra/deploy/docker-compose.production-hardening.yml` + [tls-pinning-and-signed-requests.md](./tls-pinning-and-signed-requests.md) |
| Counter replay parity | [counter-replay-parity.md](./counter-replay-parity.md) |
| Demo vertical (evaluate + case + ingest) | `infra/scripts/ci/demo_vertical_smoke.py` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `401` / auth on evaluate | Ensure `ALLOW_INSECURE_NO_AUTH=true` in `infra/deploy/.env` and recreate `core-api` |
| Health not ready | `docker compose -f infra/deploy/docker-compose.lite.yml ps` — wait for postgres/redis/core-api healthy |
| Port conflict | Stop local postgres/redis or change published ports in compose |
