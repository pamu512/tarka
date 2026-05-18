# 2. Infrastructure for proof philosophy

Date: 2026-05-07

## Status

Accepted

## Context

Fraud platforms can optimize for **detection throughput** (score fast, ship models often) or for **auditability** (reconstruct what was known, when, and why a decision was made). These goals overlap but conflict when shortcuts—non-deterministic evaluation, opaque model changes, or lossy telemetry—improve short-term detection at the expense of defensible evidence.

Tarka’s product posture is intentionally **proof-oriented**: operators, risk teams, and regulators must be able to trust that decisions are **reproducible**, **attributable**, and **durable** across the **Rust / Python hybrid** and the **triple-database** persistence model described in platform architecture.

## Decision

We **prioritize auditability over raw detection novelty** as the default architectural constraint. Concretely:

1. **Authoritative evaluation in Rust.** The rule engine path treats **`tarka-core` / `tarka_rule_engine` (Rust)** as the ground truth for deterministic evaluation semantics. Python services orchestrate IO, tenancy, and integration, but they do not silently redefine rule meaning in a way that diverges from what audit storage captured.
2. **Python for integration velocity.** **Python (FastAPI)** remains the primary language for edge APIs, workflow, and vendor adapters where ecosystem speed matters. Cross-language boundaries are explicit (typed contracts, structured logs) so Python flexibility does not erode replayability of the Rust decision core.
3. **Triple-DB stack as separation of concerns.** We standardize on three database roles (see [Architecture](../architecture.md)):
   - **PostgreSQL** — system of record for cases, configuration, graph metadata where relational integrity and transactional workflows dominate.
   - **Redis** — low-latency **ephemeral and operational state** (tags, aggregates, rate limits, caches) where loss modes are understood and bounded; not the sole home for irreplaceable evidence.
   - **ClickHouse** — **columnar analytics and evidence-scale** storage (e.g. `tarka_audit` evidence manifests) optimized for immutable, time-ordered audit queries and downstream analytics.
4. **Detection still matters—but second-class to proof when in tension.** When a feature would improve scores but weaken deterministic replay, signed evidence, or bounded retention guarantees, the feature must be redesigned or gated until the audit story is preserved.

## Consequences

### Positive

- Forensic replay and regression gates (engine vs stored decision) align with a single philosophy instead of ad hoc tooling.
- Data placement maps cleanly: operators know **where** to look for durable truth (Postgres + ClickHouse) vs **where** to expect operational cache (Redis).

### Negative

- Some “fast” ML or vendor experiments incur extra engineering to land evidence-compatible artifacts (e.g. manifests, content-addressed rules) before production rollout.

### Neutral

- This ADR does not prescribe a specific cloud vendor; it constrains **how** we use Postgres, Redis, and ClickHouse in the reference architecture so environments that claim compliance can be checked against the same invariants.
