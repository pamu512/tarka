# Services

| Service | Job |
|---------|-----|
| **decision-api** / **core-api** | Evaluate, rules/GitOps, cases macroservice |
| **orchestrator** | TransactionSchema ingest rail |
| **shadow_agent** | LLM forensics when rules request `SHADOW_REVIEW` |
| **investigation-agent** | Desk copilot + AgentRun |
| **graph-service** | Entity graph API |
| **signal-api** | Feature serving + ML scoring |
| **integration-ingress** | OSINT / Hub / vault |
| **analytics** | DuckDB/ClickHouse KPIs + trend agent helpers |
| **frontend** | UI + gateway |

Ports: [`docs/docs/guides/service-ports.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/service-ports.md).  
MkDocs service pages under `docs/docs/services/`.
