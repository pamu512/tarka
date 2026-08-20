# Architecture

Day-1 deploy is **core-api** (decision-api + case-api). Authoritative decisions: **Rust JSON packs** inside decision-api. Product vision is evaluate-first — see [`VISION.md`](https://github.com/pamu512/tarka/blob/master/VISION.md).

| Component | Role |
|-----------|------|
| core-api | `/decisions` + `/cases` gateway |
| decision-api | Evaluate, depth fusion, trend ops APIs |
| orchestrator | Ingest → evaluate → Shadow iff `SHADOW_REVIEW` |
| shadow_agent | LLM forensics / copilot (advise only, optional) |
| investigation-agent | Pack-why on evaluate-born residual cases (advise) |
| graph-service | Entity graph HTTP + decision context SoR (optional) |
| signal-api | Features + ML |
| integration-ingress | Connectors, vault/KMS |
| frontend | Analyst SPA + nginx gateway |

**Authority:** decision-api allow/deny; Shadow / trend / investigation **advise only**. Decision graph **records** chains — never overrides policy.

Cases are residual: born from evaluate → review / deny. ALLOW never becomes a case. Investigators read which pack fired and why; strategy analysts author packs.

Details: [`docs/docs/architecture.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/architecture.md) · [`docs/docs/guides/feature-data-flows.md`](https://github.com/pamu512/tarka/blob/master/docs/docs/guides/feature-data-flows.md) · [`ARCHITECTURE.md`](https://github.com/pamu512/tarka/blob/master/ARCHITECTURE.md) (evaluate/ingest wiring).
