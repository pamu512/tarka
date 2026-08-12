# Quickstart

## Fraud desk (recommended)

```bash
git clone https://github.com/pamu512/tarka.git
cd tarka
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

Smoke:

```bash
python3 scripts/oss/first_decision_smoke.py
```

Health: `GET /api/decisions/v1/health` · `GET /api/cases/v1/health`  
Evaluate: `POST /api/decisions/v1/decisions/evaluate`

## Optional rails

| Stack | Compose |
|-------|---------|
| Ingest + Shadow | `infra/deploy/docker-compose.v2-ingest.yml` |
| Trend tick | same + `--profile trend-tick` or `make trend-tick` |
| Graph | lite + `--profile graph` |

Full write-up: [`docs/docs/quickstart.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/quickstart.md).
