
## Technical Moat

Tarka is designed around a **local-first, agentic** deployment model: the orchestrator, JSON rule engine, and optional Shadow sidecar run as processes under your control on your network. Fintech teams under GDPR, PCI DSS, and bank-exam expectations routinely block or narrow third-party cloud LLM access because transaction payloads and entity identifiers are PII. Co-locating evaluation with the audit path keeps those bytes off vendor SaaS inference APIs unless you explicitly choose otherwise.

The architecture is a **deterministic–probabilistic hybrid**. The rule engine returns structured actions (for example `BLOCK` on a metadata lane match, `SHADOW_REVIEW` when amount thresholds fire) before any model hop. Shadow runs only when the ruleset requests it; connection loss and read deadlines map to defined HTTP 200 fallbacks (`FLAG` with `SIDECAR_UNREACHABLE` or deadline metadata) instead of undefined open behavior.

Efficiency is measured in-repo by `scripts/bench_ingestion.py`: **100** simultaneous `POST /v1/ingest` calls across mixed cohorts. The regression gate treats **BLOCK-cohort p99 latency** (HTTP 200 only) above **50 ms** as a failure. That threshold binds the synchronous rule path under concurrency. The harness also prints **p95** per cohort for tail visibility beyond the gate. Shadow cohort numbers are reported separately because they depend on local model hardware, not cloud round-trips.

## What is the biggest problem you are solving?

The biggest problem is the **transparency gap** between what fraud systems do in production and what a bank can later defend. Most tooling still behaves like a black box: a score or label appears next to a transaction, but the chain from raw inputs → rules → model or agent steps → final disposition is fragmented across logs, vendor consoles, and one-off analyst notes. When a regulator, customer, or court asks “why was this payment stopped?”, the organization often reconstructs intent after the fact instead of pointing at a single, queryable record tied to that transaction.

Tarka treats that gap as a product defect, not a documentation exercise. The stack is **audit-first**: a decision is treated as provisional until the rationale—rules, policy version, optional AI reasoning, and outcome—is written to a durable audit trail keyed to transaction history. Investigators and compliance read the same artifact operations relied on at decision time.

**Legacy posture:** trust accumulates around the vendor relationship, uptime dashboards, and periodic model validation. Evidence is indirect; “the system said so” is the default story.

**Audit-first posture:** trust accumulates around **verifiable rows**—immutable, relational, attributable to a specific transaction and time. The shift is from faith in an opaque pipeline to accountability in the database: if it is not in the audit log, it did not happen as a proven decision.
