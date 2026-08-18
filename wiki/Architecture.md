# Architecture

Day-1 deploy is **core-api** (decision-api + case-api). Authoritative decisions: **Rust JSON packs** inside decision-api.

| Component | Role |
|-----------|------|
| core-api | `/decisions` + `/cases` gateway |
| decision-api | Evaluate, depth fusion, trend ops APIs |
| orchestrator | Ingest → evaluate → Shadow iff `SHADOW_REVIEW` |
| shadow_agent | Local-first forensics (advise) |
| investigation-agent | Analyst copilot / AgentRun (advise) |
| graph-service | Entity graph HTTP + **decision context SoR** (SQLite) |
| signal-api | Features + ML |
| integration-ingress | Connectors, vault/KMS |
| frontend | Analyst SPA + nginx gateway |

**Authority:** decision-api allow/deny; Shadow / trend / investigation **advise only**. Decision graph **records** chains — never overrides policy.

**Accountability:** evaluate → agent advise → human disposition written fail-soft to graph-service; case Timeline and evidence bundle expose chain/impact.

Details: [`docs/docs/architecture.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/architecture.md) · [`docs/docs/guides/feature-data-flows.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/feature-data-flows.md) · [`ARCHITECTURE.md`](https://github.com/pamu512/tarka/blob/master/ARCHITECTURE.md) (evaluate/ingest).
