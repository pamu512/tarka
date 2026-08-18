# Quickstart

Get a Tarka desk stack running and evaluate a first decision.

## Prerequisites

- Docker + Compose v2
- Python 3.11+ (optional CLI)
- Git

## Day-1: fraud desk (recommended)

```bash
git clone https://github.com/pamu512/tarka.git
cd tarka

docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

This brings up **Postgres**, **Redis**, **core-api** (decision-api + case-api), **integration-ingress**, **signal-api**, and the **frontend**. Lean nav + desk-strict mocks are on by default.

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
python tarka.py install --lite    # or --all / --modules …
python tarka.py start
python tarka.py status
```

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

## Graph (optional)

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.graph-wire.yml \
  --profile graph up --build
```

Set `DECISION_GRAPH_ENABLED=1` for decision accountability chains (see [decision-context-graph](guides/decision-context-graph.md)). Prefer JanusGraph/Gremlin for the fraud-graph story; Neo4j remains available via `GRAPH_BACKEND`.

## Next

- [Architecture](architecture.md)
- [Feature data flows](guides/feature-data-flows.md)
- [Service ports](guides/service-ports.md)
