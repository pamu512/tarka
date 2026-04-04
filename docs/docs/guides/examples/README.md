# Ready-to-run examples

These guides are **copy-paste oriented**: they assume you can start a stack from [`sandbox-five-minute.md`](../sandbox-five-minute.md) or full [`deployment.md`](../deployment.md) profiles, then follow curls and UI paths.

| Example | Focus | Stack |
|--------|--------|--------|
| [Credit-card fraud (rules + ONNX)](./credit-card-fraud-onnx-rules.md) | Decision API + `ml-scoring` + rules | Lite or **core + ml** |
| [API bot / credential-stuffing defense](./api-bot-credential-defense.md) | Device-style payloads, velocity, ingress hardening | Lite |
| [IOC enrichment + graph (cyber)](./ioc-enrichment-graph.md) | OSINT aggregation + Neo4j subgraph | **Full** or **graph + integration** |

For **synthetic benchmarks** (latency / throughput on your hardware), see [`scripts/benchmarks/README.md`](../../../../scripts/benchmarks/README.md).

For **simulation-based A/B and vertical packs** (no live traffic), see [`shadow-and-ab-testing.md`](../shadow-and-ab-testing.md).
