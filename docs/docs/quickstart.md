# Quickstart

Get a Tarka desk stack running and evaluate a first decision.

## Prerequisites

- Docker + Compose v2
- Python 3.11+ (optional CLI)
- Git

## Day-1: evaluate-only (recommended)

```bash
git clone https://github.com/pamu512/tarka.git
cd tarka

docker compose -f infra/deploy/docker-compose.lite.yml up --build
```

This brings up **Postgres (Apache AGE)**, **Redis**, **graph-service**, **core-api** (decision-api + case-api), and the **frontend**. It does **not** start investigation-agent, signal-api, or integration-ingress. Desk home is `/graph` when the graph URL is set. Receipts stay at `/decisions`. Leftovers are `/leftovers`.

Thin desk (lean nav + desk-strict): also merge `infra/deploy/docker-compose.fraud-desk.yml`. Full desk / +investigation / +signals: [SRE compose profiles](operations/sre-compose-profiles.md).

**15-minute first decision:** [oss-15-minute-first-decision](guides/oss-15-minute-first-decision.md)

```bash
python3 scripts/oss/first_decision_smoke.py
```

Health (via frontend nginx or direct core-api):

- `GET /api/decisions/v1/health`
- `GET /api/cases/v1/health`

Evaluate:

`POST /api/decisions/v1/decisions/evaluate`

## Operator CLI (optional)

```bash
python3 cli.py --help
```

Day-1 remains the compose files above (`infra/deploy/`).

## Ingest + Shadow (optional)

```bash
docker compose -f infra/deploy/docker-compose.v2-ingest.yml up -d --build
```

Orchestrator (`:8790`) → decision-api → Shadow only when the action includes `SHADOW_REVIEW`.

Trend always-on tick:

```bash
docker compose -f infra/deploy/docker-compose.v2-ingest.yml --profile trend-tick up -d
# or: make trend-tick
```

## Graph

Lite already runs AGE + graph-service (`GRAPH_BACKEND=age`). Empty `GRAPH_SERVICE_URL` is evaluate-only fallback, not the product desk.

Janus / Neo4j overlay (optional, not Day-1):

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.graph-wire.yml \
  --profile graph up --build
```

Set `GRAPH_BACKEND` and `DECISION_GRAPH_ENABLED=1` for decision accountability chains (see [decision-context-graph](guides/decision-context-graph.md)).

## Next

- [Architecture](architecture.md)
- [Feature data flows](guides/feature-data-flows.md)
- [Service ports](guides/service-ports.md)
