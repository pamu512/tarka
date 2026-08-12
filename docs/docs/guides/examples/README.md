# Ready-to-run examples

These guides are **copy-paste oriented**: they assume you can start a stack from [`quickstart.md`](../../quickstart.md) or full [`deployment.md`](../deployment.md) profiles, then follow curls and UI paths.

| Example | Focus | Stack |
|--------|--------|--------|
| [Credit-card fraud (rules + ONNX)](./credit-card-fraud-onnx-rules.md) | Decision API + `ml-scoring` + rules | Lite or **core + ml** |
| [API bot / credential-stuffing defense](./api-bot-credential-defense.md) | Device-style payloads, velocity, ingress hardening | Lite |
| [Velocity counter rule keys](./velocity-counter-rule-keys.md) | Normalized `event_count_*` and `distinct_session_id_24h` for rule packs (Epic C / v1.2.0) | Lite or **core** |
| [Vertical pack benchmarks (Day 60)](../../api-reference.md) | Fixed **`seed: 42`**, `fintech` / `ecommerce` / `gaming` smoke + [thresholds](../../../../scripts/benchmarks/vertical_benchmark_thresholds.v1.json) | **core** (Decision API up) |
| [IOC enrichment + graph (cyber)](./ioc-enrichment-graph.md) | OSINT aggregation + Neo4j subgraph | **Full** or **graph + integration** |

For **synthetic benchmarks** (latency / throughput on your hardware), see [`scripts/benchmarks/README.md`](../../../../scripts/benchmarks/README.md). **Load tuning (`hey` / `k6`) is DEFERRED TO v1.3.0 (JUNE)** — May only requires reproducible simulation scorecards.

For **simulation-based A/B and vertical packs** (no live traffic), see [`shadow-and-ab-testing.md`](../shadow-and-ab-testing.md).
