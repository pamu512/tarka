# Services

| Service | Job |
|---------|-----|
| **decision-api** / **core-api** | Evaluate, rules/GitOps, cases macroservice |
| **orchestrator** | TransactionSchema ingest rail |
| **shadow_agent** | LLM forensics when rules request `SHADOW_REVIEW` |
| **investigation-agent** | Pack-why on evaluate-born residual cases; copilot + AgentRun (+ decision graph writer) |
| **graph-service** | Entity graph API + decision context SQLite SoR |
| **signal-api** | Feature serving + ML scoring |
| **integration-ingress** | OSINT / Hub / vault |
| **analytics** | DuckDB/ClickHouse KPIs + trend agent helpers |
| **frontend** | UI + gateway |

Ports: [`docs/docs/guides/service-ports.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/service-ports.md).

MkDocs service pages: `docs/docs/services/`.

Decision graph operator guide: [`docs/docs/guides/decision-context-graph.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/decision-context-graph.md).
