# Integrity & production readiness

This document is the **operator-facing summary** of what Tarka treats as **production-honest** today versus work still tracked under the **Tier-1 Honesty Program**. Canonical technical detail lives in:


| Document                                                      | Role                                                           |
| ------------------------------------------------------------- | -------------------------------------------------------------- |
| `[docs/TIER_1_HONESTY_PROGRAM.md](TIER_1_HONESTY_PROGRAM.md)` | Policy, tracks, and exit criteria                              |
| `[STUB_REGISTER.md](../STUB_REGISTER.md)`                     | Phase-0 inventory: file, surface, disposition (**SR-xx**)      |
| `[README.md](../README.md)`                                   | Architecture, evaluate path, OSINT async model, graph defaults |


If marketing or a ticket claims a capability **not** listed here as production-ready, treat it as **roadmap** until the Honesty Program row is closed.

---

## Honesty principles (non-negotiable)

1. **Durable audit plane** — Authoritative decisions, case moves, and rule governance that the product promises are **persisted** (Postgres / configured stores) before success is implied to callers.
2. **No silent Potemkin metrics** — APIs must not return **success** with fabricated KPIs, stub backtest metrics, or non-enforcing “policy” artifacts.
3. **Explicit degradation** — Upstream failure → structured **503** / `reason_code`, circuit tags, or documented **degraded** fields — not empty JSON that reads like “all fine.”
4. **Single evaluation truth for JSON rules** — Production JSON rule evaluation goes through the `**tarka_rule_engine`** Rust core (see [README](../README.md)). The product **does not** transpile visual rules to Rego; optional **OPA** remains only a **separate** HTTP step when `OPA_URL` is configured, so audit and replay stay tied to the native engine and approved JSON packs (no parallel policy artifact).

---

## Tier-1 Honesty Program — status at a glance

Workstream checklist (mirror of `[TIER_1_HONESTY_PROGRAM.md](TIER_1_HONESTY_PROGRAM.md)`; update there when scope changes):


| Track            | Topic                                                               | Status                                                                                                                                                                                 |
| ---------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Phase 0**      | Automated inventory + classification                                | **Ongoing** — maintain `[STUB_REGISTER.md](../STUB_REGISTER.md)`                                                                                                                       |
| **A**            | Feature store — Postgres + ClickHouse DDL + saga (replace `_STORE`) | **Not complete** — see SR-01 / SR-02                                                                                                                                                   |
| **B**            | Backtest — real bounded warehouse queries or remove stub run        | **Not complete** — see SR-04                                                                                                                                                           |
| **C**            | Executive KPIs — OLAP-backed or fail closed                         | **Not complete** — see SR-03                                                                                                                                                           |
| **D**            | SAR / FinCEN — durable filing + SFTP worker + ACK path              | **Not complete** as “fully shipped product” — see SR-08–SR-10 (worker/state may exist in branches; verify in your revision)                                                            |
| **E**            | Vendor marketplace — real HTTP adapters, no echo stubs in prod      | **Not complete** — see SR-06 / SR-07                                                                                                                                                   |
| **F**            | Visual rules (Rego transpile)                                       | **Deleted** / **Deprecated** — transpilation removed; `POST /v1/rules/rego/compile` → **410 Gone** tombstone only; JSON compile + Rust `tarka_rule_engine` path (**SR-05**, **SR-14**) |
| **Verification** | CI grep gates, compose integration tests, docs ↔ behavior           | **Partial** — CI enforces quality; grep gate per program doc not necessarily exhaustive                                                                                                |


---

## Production-ready surfaces (high level)

These are **suitable for production** when deployed with correct **secrets**, **migrations**, **backups**, and **observability** — not “zero engineering effort.”


| Area                                       | Production-ready?                                 | Notes                                                                                                                                                                                              |
| ------------------------------------------ | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Real-time evaluate (JSON rules)**        | **Yes** (core product)                            | Rust `tarka_rule_engine`; circuit-wrapped steps; async OSINT merge from Redis + NATS fan-out per README.                                                                                           |
| **Audit / relational case & rule storage** | **Yes** (when Postgres is the configured backend) | Alembic-managed schemas; “if it isn’t in the DB, it didn’t happen” for persisted flows.                                                                                                            |
| **Signal / feature path**                  | **Yes**                                           | Redis-backed temporal features via **signal-api** / feature-service; bounded timeouts.                                                                                                             |
| **Graph analytics**                        | **Yes** (optional component)                      | Default stack targets **JanusGraph-compatible Gremlin**; Neo4j optional with AGPL obligations (`[LICENSE-DEPENDENCIES.md](../LICENSE-DEPENDENCIES.md)`).                                           |
| **Integration OSINT worker**               | **Yes** (worker path)                             | Parallel OSINT; respect **data residency** guards where implemented; operator supplies API keys.                                                                                                   |
| **ClickHouse analytics**                   | **Yes** (optional)                                | Bounded execution time; fail-closed patterns for reporting APIs that require CH.                                                                                                                   |
| **Visual rule builder → JSON**             | **Yes**                                           | `POST /v1/rules/visual/compile` → deployable JSON pack; `POST /v1/rules/visual/evaluate-dry-run` for simulation. **No** Rego transpile; legacy `POST /v1/rules/rego/compile` returns **410 Gone**. |
| **Feature store HTTP (definitions)**       | **No** (until Track A)                            | SR-01 / SR-02 — do not treat in-process store as durable.                                                                                                                                          |
| **Backtest “run” metrics**                 | **No** (until Track B)                            | SR-04 — stub or placeholder semantics; not a compliance-grade backtest engine until closed.                                                                                                        |
| **Embedded exec KPIs**                     | **No** (until Track C)                            | SR-03 — may return nulls / notes; not silent production analytics.                                                                                                                                 |
| **SAR end-to-end regulatory filing**       | **No** (until Track D closed in your branch)      | Validate **SFTP**, **ACK**, and **state machine** in your deployment revision (SR-08–SR-10).                                                                                                       |
| **Vendor echo / demo adapters**            | **No** for prod fraud signal                      | SR-06 — gate or remove for production profiles (Track E).                                                                                                                                          |


---

## Stub Register quick link

For **file-level** truth, use the table in `[STUB_REGISTER.md](../STUB_REGISTER.md)`. Each **SR-xx** row is the contract for what must be fixed, deleted, or explicitly degraded.

---

## README “integrity status” table

The module-level story in [README — What’s Actually Shipping](../README.md) complements this page: it is **narrative posture** by slug (`core`, `analytics`, `integration`, …). `**INTEGRITY.md` + `STUB_REGISTER.md`** are the stricter engineering check for **HTTP surfaces** and **durable behavior**.

When the two diverge, **trust `STUB_REGISTER.md` and code**, then update README or this file in the same PR.