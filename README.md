# Tarka: The Graph-Powered Fraud Operating System

**Version 1.3.0-beta** · **Category: Local-First Fraud Intelligence (LFFI)**

**Vision:** End the **black box**—every material claim must be **inspectable** (rules, graph topology, local agent output), not a vendor scorecard you cannot replay.

**Prove every signal.** Not as a slogan—as a constraint: every risk claim must trace to **durable evidence** (relational audit rows, rule-engine payloads, and **graph edges you can re-walk**). If you cannot point to the vertex, the relationship type, and the observation timestamp, the signal does not ship.

**Vision (root):** [`VISION.md`](VISION.md) — paradox hook, **Tarka Triad**, market gap, **hardware as moat**.  
**Strategy narrative (extended):** [`docs/LFFI_VISION.md`](docs/LFFI_VISION.md) — LFFI, **event → identity** shift, **fraud OS** roadmap (disputes, federated signatures, ZK research).

---

## Why this exists

Legacy fraud stacks treat each transaction as a **flat record**. They miss what fraud actually is: **coordination across identities**—shared hardware, IP convergence, review rings, velocity subgraphs. Tarka is built for **relationship topology** first.

**LFFI framing:** cloud LLMs force a trade—**intelligence vs. PII residency**. Tarka breaks that by defaulting **Shadow** to **on-host inference** (Ollama) so agentic reasoning can run over the **full transaction graph** inside the VPC when you keep models local.

- **Deterministic policy** — rules that replay the same way tomorrow (Rust core, manifest capture, `tarka replay` for audit-grade diffs).
- **Graph intelligence** — JanusGraph (Gremlin) as the **fraud graph**: each ingest can materialize **vertices and typed edges** (users, devices, IPs, listings, reviews—not just rows).
- **Local-first forensics** — **Shadow** runs **on-host** inference (Ollama: **Llama 3.2** / **Qwen3-VL** class models) so cluster narratives and borderline triage can happen **without shipping raw PII to a vendor API** when you keep the model local.

---

## The graph moat

JanusGraph is not a dashboard decoration. The orchestrator’s graph client treats ingestion as **graph writes**: MERGE entities, attach **observed_at** + **transaction_id** on edges, then derive **topological signals** (degree, 2-hop neighborhoods, device overlap, IP velocity, review integrity probes).

**Implication:** a “fraud score” backed only by a scalar feature store is weak evidence. A **Gremlin-traversable** explanation path—same device across five reviewers on one listing—is **auditable**. That is the moat: **edges are the receipts**.

Configure graph backend via deployment env (JanusGraph remote / Gremlin; Neo4j remains available in some paths—see `deploy/janusgraph-cassandra-demo/` and orchestrator `GRAPH_BACKEND` docs in code).

---

## Local-first agentic AI (Shadow)

Shadow is a **sidecar**, not a black box in someone else’s region:

- **Input:** the same **TransactionSchema** contract as the rest of the ingest rail.
- **Inference:** **Ollama** by default (`SHADOW_LLM_BACKEND=ollama`); optional remote backends exist, but **1.3.0-beta** assumes you care about **VPC / laptop containment**.
- **Output:** structured **ShadowDecision** JSON + **AuditLog** persistence when the rule path demands human-grade review (`SHADOW_REVIEW` and related actions).

**Operational fact:** if the model never leaves your metal, your **cluster forensics** stay inside your trust boundary. You still own retention, redaction, and export policy.

---

## System of record: from events to investigations

Tarka **1.3.0-beta** moves the operator mental model from “another alert fired” to **an investigation with a state machine**:

- **Lifecycle cases** (`lifecycle_cases`) anchor to **audit log** rows—disposition without a durable row is incomplete.
- **States** (orchestrator `CaseStatus`): `OPEN` → `UNDER_REVIEW` → `PENDING_ACTION` → `RESOLVED_FRAUD` / `RESOLVED_LEGIT`, with **explicit reopen rules** when you walk back from a terminal state (non-empty `reopen_reason` where required).

Shadow’s `cases` table remains the forensic anchor for sidecar work; product **case management** is the **investigation** layer on top of committed audit evidence—not a stream of disposable events.

---

## Hardware baseline (full stack)

Target machine for **Gremlin + local LLM + rule evaluation + Postgres/Redis sidecars**:

| Baseline | Spec |
|----------|------|
| **SoC** | **Apple M5 Pro** (or equivalent many-core host) |
| **RAM** | **24 GB** minimum for the **full** beta profile (JanusGraph-adjacent services, Ollama with **Llama 3.2** / **Qwen3-VL:30b-class** weights, Rust engine + Python orchestration). |
| **Disk** | **SSD**, **≥ 40 GB** free once you count container layers + model weights. |
| **Software** | **Docker Compose v2**, **Python ≥ 3.11**, **Ollama** on `127.0.0.1:11434` (override with `OLLAMA_BASE` in bootstrap). |

Smaller hosts run **subgraphs** of the stack; do not expect comfortable local inference below **24 GB**.

---

## Technical stack (1.3.0-beta)

| Layer | What ships |
|--------|------------|
| **Decision engine** | **Rust `tarka-core`** — deterministic evaluation, WASM leaf hooks, forensic **replay** (`crates/tarka-cli`, `tarka replay`). Python integration uses **PyO3** where the `tarka` / `tarka-py` bindings are installed (compiler / flowchart / advanced paths). **HTTP policy seam:** `tarka_v2_core/services/rule_engine` (FastAPI evaluator on the ingest rail). |
| **Intelligence graph** | **JanusGraph** (Gremlin) for topological signals; demo compose under `deploy/janusgraph-cassandra-demo/`. |
| **Forensics AI** | **Shadow** — FastAPI sidecar `tarka_v2_core/services/shadow_agent`; local **Ollama** models (**Llama 3.2**, **Qwen3-VL** per `scripts/bootstrap_beta.sh` baseline checks). |
| **Visualizer** | **Next.js** (`tarka_v2_ui/`) — **Knowledge Drop Zone** in decision views: upload priming documents, forward to `POST /v1/investigation/prime`, merge **graph snippet + cluster analysis** into analyst-facing UI (`DecisionDetail`, `KnowledgeDropInsight`). |
| **Persistence** | **Postgres** (async SQLAlchemy), Redis where configured; **AuditLog** as the non-negotiable write-ahead for automated decisions. |

---

## Install and run (beta)

From the **repository root** with Docker running:

```bash
# 1) Strict preflight: Docker, Compose, Python 3.11+, RAM sanity, Ollama baseline model
./scripts/bootstrap_beta.sh

# 2) Bring up the compose stack (repo-root docker-compose.yml unless DOCKER_COMPOSE_FILE overrides)
./scripts/bootstrap_beta.sh --launch
```

**Unified Python operator CLI** (module install / multi-profile compose)—this is the **`tarka start` path** people mean in ops docs today (`tarka.py` is the entrypoint):

```bash
python tarka.py install --lite    # or --all / --modules …
python tarka.py start              # start what you installed
python tarka.py status
```

**Rust operator CLI** (`tarka` binary: forensic replay today—not `start`; use bootstrap or `tarka.py` for compose lifecycle):

```bash
cargo build --release -p tarka-cli
./target/release/tarka replay <MANIFEST_UUID>   # ClickHouse + registry + diff vs captured audit
```

**Deep links:** [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) (ingest / Shadow bypass), [`docs/onboarding.md`](docs/onboarding.md) (broader platform), [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Repository map (short)

| Path | Role |
|------|------|
| [`tarka_v2_core/`](tarka_v2_core/) | Ingestor schema, orchestrator, **rule_engine**, **shadow_agent**, shared models. |
| [`tarka_v2_ui/`](tarka_v2_ui/) | Next.js operator UI + Knowledge Drop / prime API routes. |
| [`crates/tarka-core/`](crates/tarka-core/) | Rust decision DAG / determinism. |
| [`crates/tarka-cli/`](crates/tarka-cli/) | `tarka replay` and operator tooling. |
| [`scripts/bootstrap_beta.sh`](scripts/bootstrap_beta.sh) | **1.3.0-beta** gate + `--launch`. |
| [`legacy_attic/`](legacy_attic/) | Archived monolith-era trees—reference only. |

---

## License

Application code is **Apache-2.0** unless a subdirectory states otherwise. Third-party graph/database runtimes carry their own licenses—see **`LICENSE-DEPENDENCIES.md`** when you enable them.
