# Tarka: The Graph-Powered Fraud Operating System

**Version 1.3.0-beta** · **Category: Local-First Fraud Intelligence (LFFI)**

**Vision:** End the **black box**—every material claim must be **inspectable** (rules, graph topology, local agent output), not a vendor scorecard you cannot replay.

**Prove every signal.** Not as a slogan—as a constraint: every risk claim must trace to **durable evidence** (relational audit rows, rule-engine payloads, and **graph edges you can re-walk**). If you cannot point to the vertex, the relationship type, and the observation timestamp, the signal does not ship.

**Vision:** [`VISION.md`](VISION.md) — paradox hook, **Tarka Triad**, market gap, optional local inference.  
**Operator docs:** [`docs/INDEX.md`](docs/INDEX.md) · [feature data flows](docs/docs/guides/feature-data-flows.md) · [`STUB_REGISTER.md`](STUB_REGISTER.md).

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

### Decision accountability graph

Beyond AuditLog and traces, Tarka records **decisions as first-class objects** (evaluate → agent advise → human disposition) with causal chains you can query months later—without replaying LLM conversations.

**How it works**

1. **Evaluate** — After decision-api finishes allow/deny/review, a background writer posts an `evaluate` decision to graph-service (rule ids, outcome, defendable `reasoning`, `trace_id`, `audit_log_id`). Policy authority stays in Rust; the graph only records what happened.
2. **Agent advise** — When investigation-agent persists an AgentRun (chat, shadow, trend), it records `agent_advise` and auto-links `INFLUENCED` from the latest evaluate on the same trace.
3. **Human disposition** — When an analyst applies case status (maker-checker), case-api records `human_disposition` and links `CAUSED` from the latest agent advise on the case (or evaluate on trace if no agent step).

Writers are **fail-soft**: if graph-service is down, evaluate/ingest/case flows still succeed. The graph never overrides allow/deny.

```
trace tx-abc
  evaluate (review, velocity_spike) ──INFLUENCED──► evaluate (re-run)
         └──INFLUENCED──► agent_advise (cluster narrative)
                                    └──CAUSED──► human_disposition (escalated)
```

**Where to look**

| Surface | Purpose |
|---------|---------|
| graph-service `/v1/decisions/*` | SQLite SoR — search, chain, impact, invalidate |
| case-api `/v1/cases/{id}/decisions` | Desk proxy (merges case + trace scope) |
| Case Timeline → **Decision accountability** | Chain / impact per row |
| Evidence bundle `decision_context` | Signed export block (`tarka.decision_context/v1`) |
| `scripts/compliance/export_decision_prov.py` | W3C PROV-O JSON-LD |

**Enable:** `DECISION_GRAPH_ENABLED=1` + `GRAPH_SERVICE_URL` with the graph compose profile (`infra/deploy/docker-compose.graph-wire.yml`). Smoke: `python3 scripts/oss/decision_context_chain_smoke.py`.

Full operator guide (API tables, MCP tools, Semantica sidecar): [`docs/docs/guides/decision-context-graph.md`](docs/docs/guides/decision-context-graph.md).

---

## Production shape (Linux + Compose)

Default is a **Linux VM** and Docker Compose — not a laptop triad. Day-1 is **desk** (~8 GB): decision + cases. Graph, async ingest, and local Shadow are add-on profiles.

SRE: [compose profile runbook](docs/docs/operations/sre-compose-profiles.md) (capacity, health, what pages, what degrades).

---

## Performance & Benchmarks

Reproduce **local** figures only from this README. Hypothetical enterprise scale-out projections (if any) live exclusively in [`scripts/benchmarks/README.md`](scripts/benchmarks/README.md) and must never be cited as shipped SLOs.

**Local / CI baseline:** Linux or any Docker host that can run **desk** (~8 GB); Redis single-node; lite compose on SSD. Bring up Decision API on `http://127.0.0.1:8000`, then:

```bash
python scripts/benchmarks/vertical_benchmark_smoke.py --seed 42 --threshold strict
```

Also see [`latency_evaluate.py`](scripts/benchmarks/latency_evaluate.py) and [`.github/workflows/counter-parity-smoke.yml`](.github/workflows/counter-parity-smoke.yml). Publish honest numbers: host SKU, compose profile, commit SHA, warm-up count, payload schema.

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

## Start here (fraud desk)

Day-1 path — **decision + cases**, no JanusGraph/Ollama required (~8 GB Linux host):

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

Enforces lean nav + `VITE_DESK_STRICT` (case/calibration/QA never auto-mock).  
**15-minute first decision:** [docs/docs/guides/oss-15-minute-first-decision.md](docs/docs/guides/oss-15-minute-first-decision.md) → `python3 scripts/oss/first_decision_smoke.py`

### Optional add-ons (after desk works)

Graph (`--profile graph`) and local Shadow/Ollama are **not** the production default. Size them from the [SRE compose runbook](docs/docs/operations/sre-compose-profiles.md). Do not colocate Janus + Ollama on the evaluate host.

```bash
./scripts/bootstrap_beta.sh --launch
# or Lite with graph: docker compose -f infra/deploy/docker-compose.lite.yml --profile graph up --build
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
