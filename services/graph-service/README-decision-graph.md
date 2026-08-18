# Decision context graph (graph-service)

Accountability layer: decisions as durable objects with causal chains.

**Operator guide:** [`docs/docs/guides/decision-context-graph.md`](../../docs/docs/guides/decision-context-graph.md)

## Quick enable

```bash
export DECISION_GRAPH_ENABLED=1
export GRAPH_DATA_DIR=/var/tarka-graph
```

With lite + graph profile, use `infra/deploy/docker-compose.graph-wire.yml`.

## API

- `POST /v1/decisions` — record
- `GET /v1/decisions/search` — filter
- `GET /v1/decisions/{id}/chain` — causal parents
- `GET /v1/decisions/{id}/impact` — blast radius

See `src/graph_service/decision_context_store.py` and OpenAPI `contracts/openapi/graph-service.yaml`.

## Tests

```bash
cd services/graph-service
PYTHONPATH=src:.:../shared pytest tests/test_decision_context.py -q
```
