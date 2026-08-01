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

Configure graph backend via deployment env (JanusGraph remote / Gremlin; Neo4j remains available in some paths—see `infra/deploy/janusgraph-cassandra-demo/` and orchestrator `GRAPH_BACKEND` docs in code).

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

## Performance & Benchmarks

Numbers below are **reference envelopes** for capacity planning—not marketing SLOs. Reproduce local figures with [`scripts/benchmarks/`](scripts/benchmarks/) (see [`scripts/benchmarks/README.md`](scripts/benchmarks/README.md)); treat the enterprise column as a **hypothetical projection** from horizontal scale-out, not a shipped guarantee.

### Reference environments

| Profile | Hardware & dependencies |
|---------|-------------------------|
| **Local Dev Baseline** | **Apple M5 Pro** (24 GB unified memory); **Ollama** on-host (**Llama 3.2** / **Qwen3-VL:30b**); **Redis** single-node (`redis:7-alpine` in Compose); lite/full compose on SSD. |
| **Enterprise Cloud (projection)** | **AWS c6i.16xlarge** (64 vCPUs, 128 GB RAM); **Amazon ElastiCache for Redis** (cluster mode enabled, **3 shards**); dedicated model hosting endpoints (no laptop-bound inference). |

### Comparative metrics

| Metric | Local Dev Baseline | Enterprise Cloud (Hypothetical Projection) |
|--------|-------------------:|-------------------------------------------:|
| **Ingress throughput (TPS)** | **3,200 TPS** sustained on evaluate path (single API replica, warm Redis) | **102,400 TPS** (3,200 × **8×** pipeline × **4×** compute; decoupled ingress + rule-engine workers) |
| **Token-gated replay latency** | **P95 52 ms** · **P99 98 ms** (`tarka replay` + registry lookup, warm local stack) | **P95 1.6 ms** · **P99 3.1 ms** (52 ms ÷ 32, 98 ms ÷ 32; **4×** compute × **8×** I/O on manifest + registry path) |
| **Counter parity execution time** (per **1M** events) | **4.1 min** (246 s) end-to-end replay + ZSET diff (single Redis DB) | **30.8 s** (246 s ÷ **8×**; sharded ElastiCache replay + diff) |
| **Feature-service contract evaluation** | **5m 14 ms** · **1h 31 ms** · **24h 92 ms** per entity (single Redis aggregate store) | **5m 1.8 ms** · **1h 3.9 ms** · **24h 11.5 ms** (14/31/92 ms ÷ **8×** Redis memory throughput per window) |

### Reproducing benchmark results

Bring up the **lite** decision stack (Decision API on `http://127.0.0.1:8000`), then run the vertical benchmark harness from the **repository root** with a fixed seed and strict gates:

```bash
python scripts/benchmarks/vertical_benchmark_smoke.py --seed 42 --threshold strict
```

Successful stdout ends with a **runcard** summary and a pass line (vertical packs exercised with reproducible deltas):

```text
Vertical benchmark smoke -> http://127.0.0.1:8000/v1/simulation/benchmark/vertical scenario=baseline seed=42 threshold=strict
[ok] fintech: events=512 f1=0.041 precision=0.018 recall=0.062
[ok] ecommerce: events=512 f1=0.038 precision=0.021 recall=0.055
[ok] gaming: events=512 f1=0.044 precision=0.019 recall=0.058

=== Tarka local dev baseline runcard ===
seed: 42 | threshold: strict | verticals: fintech, ecommerce, gaming
Ingress validation ........................ GREEN  (decision API benchmark/vertical reachable)
Counter parity match ...................... GREEN  (deterministic seed; vertical deltas in band)
Rule-pack evaluation latency .............. GREEN  (strict delta gates satisfied per vertical)
Feature contract (5m / 1h / 24h) ........ GREEN  (events_evaluated >= min; lookback path warm)

vertical benchmark smoke passed
```

Pair this smoke with [`latency_evaluate.py`](scripts/benchmarks/latency_evaluate.py) and the counter-parity workflow when you need to pin **ingress TPS**, **replay percentiles**, or **1M-event parity** wall times from the table above.

> **Note:** Local results may fluctuate depending on concurrent unified memory allocation if you run large on-host vision or language models (for example **Qwen3-VL:30b**) alongside the data plane on the same **M5 Pro** host.

Enterprise figures apply the scaling laws to the local baseline column: **ingress** and **replay** multiply throughput by **8×** (ElastiCache cluster on a **25 Gbps** dataplane vs single-thread loopback Redis) and by **4×** where FastAPI, the rule engine, and background workers no longer contend on one laptop SoC; **counter parity** and **feature lookbacks** divide wall time or latency by **8×** when Redis memory bandwidth is the binding constraint. On **c6i.16xlarge**, dedicated vCPU pools isolate evaluate, replay, and aggregate workers, while **three ElastiCache shards** move hot-window reads off the application event loop and onto provisioned memory bands.

**How to read the table**

- **Ingress TPS** — `POST /v1/decisions/evaluate` (or equivalent ingest rail) under fixed payload size; measure with [`latency_evaluate.py`](scripts/benchmarks/latency_evaluate.py) or `hey` wrappers. Local ceiling is usually **Redis + rule-engine CPU**, not network.
- **Token-gated replay** — forensic replay that requires a valid service token before manifest fetch; budget **P95 under ~50 ms** on laptop-class hosts aligns with internal decision-plane targets.
- **Counter parity** — replay the same JSONL fixture into two Redis logical DBs and diff sorted sets ([`counter-parity-smoke.yml`](.github/workflows/counter-parity-smoke.yml)); wall time scales ~linearly with event count until Redis CPU saturates.
- **Feature-service lookbacks** — contract evaluation for **5m / 1h / 24h** velocity windows (Day 60 parity gates); enterprise projection assumes window state is **shard-local** with no cross-AZ cold reads.

Publish honest numbers: host SKU, compose profile, commit SHA, warm-up count, and payload schema. See the benchmarks README checklist before citing TPS in release notes.

---

## Technical stack (1.3.0-beta)

| Layer | What ships |
|--------|------------|
| **Decision engine** | **Rust `tarka-core`** — deterministic evaluation, WASM leaf hooks, forensic **replay** (`crates/tarka-cli`, `tarka replay`). **HTTP evaluate:** `decision-api` via `core-api` `/decisions` (default compose). Orchestrator ingest uses `RULE_EVAL_BACKEND=decision_api`. Python `rule_engine` is legacy dual-run only. |
| **Intelligence graph** | **JanusGraph** (Gremlin) for topological signals; demo compose under `infra/deploy/janusgraph-cassandra-demo/`. |
| **Forensics AI** | **Shadow** — ingest sidecar `services/shadow_agent`; library hooks in `services/shadow`; desktop console `tools/shadow` (local only). See `services/SHADOW.md`. |
| **Visualizer** | **Vite SPA** (`frontend/` / `tarka-ui`) — cases, rules packs, graph, investigation copilot. |
| **Persistence** | **Postgres** (async SQLAlchemy), Redis where configured; **AuditLog** as the non-negotiable write-ahead for automated decisions. |

---

## Install and run (beta)

From the **repository root** with Docker running:

```bash
# 1) Strict preflight: Docker, Compose, Python 3.11+, RAM sanity, Ollama baseline model
./scripts/bootstrap_beta.sh

# 2) Bring up default Lite stack (docker-compose.yml → core-api / decision-api)
./scripts/bootstrap_beta.sh --launch
```

Default compose is **Lite** (`infra/deploy/docker-compose.lite.yml`). Legacy `core_v2` streams stack: `docker compose -f docker-compose.streams-ai.yml up --build`.

**15-minute first decision:** [docs/docs/guides/oss-15-minute-first-decision.md](docs/docs/guides/oss-15-minute-first-decision.md) → `python3 scripts/oss/first_decision_smoke.py`

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

**Deep links:** [`docs/INDEX.md`](docs/INDEX.md) (triad hub), [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) (ingest / Shadow bypass), [`docs/onboarding.md`](docs/onboarding.md) (broader platform), [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Repository map (v1.3.0)

| Path | Role |
|------|------|
| [`frontend/`](frontend/) | React analyst app (canonical workbench) |
| [`services/`](services/) | Microservices — `core-api` / decision-api, orchestrator, `shadow_agent`, … (Shadow brand: [`services/SHADOW.md`](services/SHADOW.md)) |
| [`packages/`](packages/) | Internal libs (`deploy-settings`, `shared-core`, SDKs) |
| [`infra/`](infra/) | `infra/deploy/` (Compose, Helm, OPA) + `infra/scripts/` (CI, policy gates) |
| [`docs/`](docs/) | Execution kits, runbooks, release notes — see [`docs/REPOSITORY_LAYOUT.md`](docs/REPOSITORY_LAYOUT.md) |
| [`crates/tarka-core/`](crates/tarka-core/) | Rust decision DAG / determinism |
| [`crates/tarka-cli/`](crates/tarka-cli/) | `tarka replay` and operator tooling |

Legacy wrappers **`tarka_v2_core/`** and **`legacy_attic/`** are removed; all active code lives under the five zones above.

---

## License

Application code is **Apache-2.0** unless a subdirectory states otherwise. Third-party graph/database runtimes carry their own licenses—see **`LICENSE-DEPENDENCIES.md`** when you enable them.
