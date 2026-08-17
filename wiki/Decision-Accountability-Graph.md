# Decision accountability graph

Records **decisions as durable objects** — evaluate, agent advise, human disposition — with causal chains you can query without replaying LLM logs.

## Flow

1. **Evaluate** — decision-api background writer → graph-service (`kind=evaluate`)
2. **Agent advise** — investigation-agent AgentRun persist → auto-links prior evaluate on `trace_id`
3. **Human disposition** — case-api status apply → links agent advise or evaluate

Writers are **fail-soft**. Decision-api remains sole **allow/deny** authority.

## Enable

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.graph-wire.yml \
  --profile graph up --build
```

| Env | Purpose |
|-----|---------|
| `DECISION_GRAPH_ENABLED=1` | Turn on store + writers |
| `GRAPH_SERVICE_URL=http://graph-service:8001` | Client target |
| `GRAPH_DATA_DIR=/var/tarka-graph` | Persist SQLite |

Smoke: `python3 scripts/oss/decision_context_chain_smoke.py`

## Desk

Case workbench → **Timeline** → **Decision accountability** panel (chain / impact per decision).

## Full guide

[`docs/docs/guides/decision-context-graph.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/decision-context-graph.md)
