# Decision context graph (A+B) — native SoR + Semantica sidecar

**Date:** 2026-08-17  
**Status:** Implemented (Waves 1–4 + depth: auto-link, case UI, Janus mirror, PROV export)  
**Related:** [AgentRun spine](./2026-08-13-agent-run-spine-design.md), [Omniscient AgentRun](./2026-08-11-omniscient-agent-run-design.md), [AI productionization](./2026-08-12-ai-productionization-design.md)

## Goal

Make Tarka answer, months later, without log archaeology:

- What facts were available when this decision was made?
- Which earlier decision caused or influenced it?
- Where did those facts come from, and have they been invalidated since?
- Have we made a similar decision before?
- What downstream decisions depended on this one?
- Did it pass a deterministic policy check (rule ID / pack)?

**A — Native:** graph-service owns a durable **decision context graph** (SoR).  
**B — Sidecar:** optional Semantica mirror for demo / export / MCP experimentation — **never** authority for allow/deny.

## Philosophy (unchanged)

- Decision-api / Rust packs remain sole allow/deny authority.
- AI records **advise / propose** decisions; humans and rules record **binding** decisions.
- Semantica Rete / SPARQL / Datalog stay **advise-only**. Do not import a second production rule engine.
- Missing graph → `freshness=missing` / `graph_missing=true`; never invent edges.
- Writers are fire-and-forget from evaluate / AgentRun / case disposition — parent request must not fail if the decision-graph write fails (log + metric).

## Non-goals

- Replacing Janus/AGE with Semantica’s in-memory `ContextGraph` as production store.
- Running Semantica extractors as the primary fraud entity-resolution pipeline.
- Storing hidden LLM chain-of-thought in `reasoning` (store defendable rationale only: evidence IDs, rule IDs, thresholds, human override).
- Auto-resolving cases or auto-promoting Wasm from causal blast-radius.

---

## A — Native decision graph (SoR)

### Data model

New vertex label **`Decision`** (add to graph-service `ALLOWED_LABELS` / tenant schema allowlist).

| Property | Type | Notes |
|----------|------|-------|
| `tenant_id` | string | required |
| `external_id` | string | stable id (`dec_<uuid>` or hash of `(tenant, kind, audit_log_id\|agent_run_id\|case_event_id)`) |
| `kind` | enum | `evaluate` \| `agent_advise` \| `human_disposition` \| `policy_gate` |
| `category` | string | e.g. `transaction_evaluate`, `case_status_propose`, `sar_file` |
| `scenario` | string | short human-readable scenario |
| `outcome` | string | `allow` / `review` / `deny` / proposed status / etc. |
| `confidence` | float? | optional; omit when N/A |
| `reasoning` | string | defendable rationale only |
| `rule_ids` | list[string] | deterministic policy that fired |
| `audit_log_id` | string? | link to `audit_logs` |
| `agent_run_id` | string? | link to AgentRun |
| `case_id` | string? | investigation or lifecycle case id |
| `trace_id` | string? | |
| `entity_external_ids` | list[string] | primary subjects |
| `evidence_ids` | list[string] | from context snapshot / bundle |
| `created_at` | ISO datetime | decision time (temporal point) |
| `invalidated_at` | ISO datetime? | soft invalidate |
| `invalidation_reason` | string? | |
| `semantica_decision_id` | string? | mirror id when B enabled |

**Edges (relationship types, uppercase):**

| Rel | From → To | Meaning |
|-----|-----------|---------|
| `BASED_ON` | Decision → Entity \| Document \| Payment | facts / subjects considered |
| `GOVERNED_BY` | Decision → Custom(`PolicyRule`) or property-only | optional; v1 may keep `rule_ids` on vertex only |
| `CAUSED` | Decision → Decision | hard causal parent → child |
| `INFLUENCED` | Decision → Decision | soft influence |
| `PRECEDENT_FOR` | Decision → Decision | explicit precedent link (optional; search may be vector/heuristic) |
| `RECORDED_BY` | Decision → Custom(`AgentRun`) or property | v1: property `agent_run_id` is enough |
| `SUPERSEDES` | Decision → Decision | later correction / invalidation replacement |

v1 ships: vertex props + `BASED_ON` + `CAUSED` / `INFLUENCED` / `SUPERSEDES`. Precedent search can be property/filter first; embedding later.

### Writers

| Source | When | Decision `kind` | Causal links |
|--------|------|-----------------|--------------|
| decision-api evaluate | after authoritative outcome (incl. shadow tag) | `evaluate` | `BASED_ON` primary entity (+ device/account if present); link prior evaluate for same `trace_id` / entity window as `INFLUENCED` when metadata provides `prior_decision_id` |
| investigation-agent AgentRun persist | after chat / shadow / trend internal POST | `agent_advise` | `BASED_ON` entities from snapshot; `INFLUENCED` by evaluate decision for same `trace_id` / `case_id` when resolvable |
| case-api disposition / status confirm | on human status / disposition | `human_disposition` | `CAUSED` or `INFLUENCED` by pending `agent_advise` proposal if one was confirmed; `SUPERSEDES` prior open disposition if any |

**Fail-soft:** graph upsert via existing graph-service HTTP client; 2s timeout; warn metric `decision_graph_write_fail`; never raise to client.

**Shadow evaluate:** still write Decision with tag/property `shadow=true` so blast-radius works; do not imply enforcement occurred.

### Readers (graph-service HTTP)

| Endpoint | Behavior |
|----------|----------|
| `POST /v1/decisions` | upsert Decision + optional edges |
| `GET /v1/decisions/{external_id}` | get + neighbor summary |
| `GET /v1/decisions/{id}/chain` | walk inbound `CAUSED`/`INFLUENCED` (depth cap) |
| `GET /v1/decisions/{id}/impact` | walk outbound causal / influence (blast radius) |
| `GET /v1/decisions/search` | filter by tenant, entity, category, outcome, time range; optional text match on scenario/reasoning |
| `POST /v1/decisions/{id}/invalidate` | set `invalidated_at` + reason; optional `SUPERSEDES` to replacement |

Auth: existing graph-service / RBAC (`analyst`+ for read; `service` or internal secret for write from evaluate/AgentRun).

### Provenance (native, lean)

Do **not** stand up a second PROV-O database in v1.

- Evidence: reuse `tarka.evidence_bundle/v1`, AgentRun `evidence_ids`, vendor signal `provenance`.
- Invalidation: Decision soft-invalidate + audit comment / case note.
- Optional later: export adapter to W3C PROV-O JSON-LD for compliance packs (`scripts/compliance/`).

### MCP (native)

New small service or module under `services/investigation-agent` or `tools/mcp-tarka/`:

Tools wrap existing APIs:

- `record_decision`, `get_decision_chain`, `get_decision_impact`, `find_precedent_decisions`
- existing: `get_case`, `subgraph`, `propose_case_status` (already HIL)

This is the product MCP plane. Semantica MCP (B) is optional and clearly labeled experimental.

### Desk UI (thin)

Case / entity timeline: Decision chips with outcome, kind, link to chain/impact. No duplicate accountability surface in v1.

---

## B — Semantica sidecar (optional proof)

### Placement

```
evaluate / AgentRun / disposition
        │
        ├─► graph-service Decision SoR          (A, always when feature on)
        └─► semantica-bridge (optional)         (B, feature flag)
                 │
                 └─► Semantica ContextGraph process
                      (record_decision, add_causal_relationship,
                       find_similar_decisions, analyze_decision_impact)
```

### Feature flags / env

| Var | Default | Purpose |
|-----|---------|---------|
| `DECISION_GRAPH_ENABLED` | `0` | native writers/readers |
| `SEMANTICA_BRIDGE_ENABLED` | `0` | mirror to Semantica |
| `SEMANTICA_URL` / process mode | — | HTTP or in-process pin |
| `SEMANTICA_PIN` | required if B on | pinned package version or git SHA |

### Rules for B

1. Pin Semantica version; document in bridge README.
2. On mirror failure: log only; native SoR remains correct.
3. Store `semantica_decision_id` on native Decision when mirror succeeds.
4. Semantica reasoning engines: **never** wired into evaluate allow/deny path.
5. Compose profile `semantica` (optional) — not in default desk stack.
6. Spike acceptance: offline script records 3 linked decisions, prints chain + impact, asserts native GET chain matches mirror chain IDs mapping.

### What we take from Semantica vs what we ignore

| Take | Ignore / defer |
|------|----------------|
| Decision-as-object API shape | Production KG built only via Semantica ingest |
| CAUSED / INFLUENCED / PRECEDENT_FOR vocabulary | Rete as compliance gate |
| Precedent + blast-radius UX patterns | Replacing Janus |
| MCP tool naming patterns | Unpinned `semantica[all]` in prod images |

---

## Rollout waves

| Wave | Deliverable | Verify |
|------|-------------|--------|
| **0** | Spec + OpenAPI sketch + label allowlist change plan | this doc approved |
| **1** | graph-service Decision CRUD + chain/impact + unit tests | pytest graph-service |
| **2** | evaluate + AgentRun + disposition writers (fail-soft) | golden smoke: 1 evaluate → 1 advise → 1 human chain |
| **3** | Native MCP tools + case timeline chips | MCP smoke + UI smoke |
| **4** | Semantica bridge profile + pin + offline parity script | bridge smoke; flag off by default |

---

## Success criteria

1. For a seeded case, `GET .../chain` returns evaluate → agent_advise → human_disposition without reading application logs.
2. Invalidating an evaluate Decision surfaces on impact walk for downstream advise/disposition.
3. With `SEMANTICA_BRIDGE_ENABLED=0`, full desk path works; with `=1`, mirror IDs populate and spike script passes.
4. No path exists where Semantica outcome overrides Rust/evaluate authority.
5. Parent evaluate/ingest latency SLO unchanged when graph write times out (async/fail-soft).

## Open questions (resolve before Wave 1 code)

1. Decision vertices in Janus vs AGE-only first? **Proposal:** all backends that support Custom labels — start Janus (default) + in-memory test double.
2. Precedent: property search only in Wave 1–2, or ship embedding index? **Proposal:** filter/search first; embeddings later.
3. Where does MCP process live? **Proposal:** `services/tarka-mcp/` thin stdio server calling HTTP APIs (keeps investigation-agent free of MCP protocol churn).
