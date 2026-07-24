# Design: One Rust rule engine via orchestrator → decision-api (Approach A)

**Date:** 2026-07-11  
**Status:** Phases 0–3 complete — decision-api is default evaluate path  
**Goal:** Single Rust rule engine (decision-api FFI). Orchestrator ingest uses decision-api evaluate instead of Python `services/rule_engine` (:8778). Then declutter (delete Python sidecar, dual trees, etc.).

---

## 1. Problem

Today there are two rule systems:

| Path | Runtime | Contract |
|------|---------|----------|
| decision-api evaluate | Rust PyO3 (`packages/tarka-rule-engine`) + optional Python pack fallback | Feature map → `decision` / `score` / `tags` / `rule_hits` |
| orchestrator `/v1/ingest` | Python HTTP `services/rule_engine` :8778 | `TransactionSchema` → `actions[]` (`BLOCK` / `ALLOW` / `FLAG` / `SHADOW_REVIEW`) |

They share a name, not an implementation. Consolidation target: **one engine (Rust packs)**, multiple APIs fine, orchestrator calls decision-api.

---

## 2. Non-goals (this design)

- Rewriting decision-api’s evaluate path (already Rust-primary).
- Moving Shadow / Lekh / outbox into decision-api (orchestrator stays the ingest glue).
- Building a new shared IR or compiling transaction AST ↔ packs in v1 (deferred).
- Deleting `tarka_v2_ui` / legacy_v1 in this workstream (declutter phase after cutover).

---

## 3. Target architecture

```
TransactionSchema
    → orchestrator /v1/ingest
        → map_tx_to_evaluate_request()
        → POST {DECISION_API_URL}/v1/decisions/evaluate
        → map_evaluate_to_actions()   # explicit policy
        → existing Shadow / Lekh / outbox / NATS paths
```

**Delete after parity:** `services/rule_engine` FastAPI sidecar and `RULE_ENGINE_URL` for evaluate.  
**Keep temporarily:** any in-process imports of `rule_engine.ast_schemas` used only by shadow-test / hypothesis tools — migrate or stub in a follow-up.

**Canonical engine:** `packages/tarka-rule-engine` (Rust) via decision-api `evaluate_json_rules` / FFI.

---

## 4. Feature mapping (`TransactionSchema` → `EvaluateRequest`)

Orchestrator builds:

```text
EvaluateRequest(
  tenant_id      = required: metadata.tenant_id | X-Tenant-Id  (else 422)
  event_type     = metadata.event_type if valid EventType else "payment"
  entity_id      = str(transaction.entity_id)
  session_id     = metadata.session_id | None
  region         = metadata.region | "global"
  payload        = {
                     "amount": transaction.amount,
                     "timestamp": transaction.timestamp (ISO),
                     "country": transaction.country if present,
                     **flatten(transaction.metadata) under agreed keys
                   }
  metadata       = transaction.metadata (pass-through)
  device_context = from metadata.device_* if present
)
```

**Rules:**

- Do not invent PII fields beyond what the envelope already carries.
- Graph enrichment that Python sidecar did via Neo4j (`graph_linked_to_blocked_count`) moves to decision-api’s existing graph path (already on evaluate) — orchestrator must not call Neo4j for rule fields after cutover.
- Mapping is a pure function in orchestrator (`decision_evaluate_bridge.py`) with unit tests for field coverage.

---

## 5. Action-mapping policy (`EvaluateResponse` → `actions[]`)

Orchestrator today requires `actions` including optional `BLOCK` / `SHADOW_REVIEW` / `FLAG` / `ALLOW`. Decision-api returns `decision` ∈ `{allow, review, deny}` plus `score`, `tags`, `rule_hits`, `recommended_action`.

**v1 policy (explicit, versioned string `action_map_v1`):**

| Decision-api | Orchestrator actions |
|--------------|----------------------|
| `decision == "deny"` | `["BLOCK"]` |
| `decision == "review"` | `["SHADOW_REVIEW", "FLAG"]` |
| `decision == "allow"` | `["ALLOW"]` |

**Overrides (applied after table, still `action_map_v1`):**

1. If `recommended_action` is challenge / step-up family → ensure `FLAG` present (do not remove `BLOCK`).
2. If tags contain `shadow_review` or rule_hits contain configured prefix `shadow:` → ensure `SHADOW_REVIEW`.
3. Never drop `BLOCK` when `decision == "deny"`.

**Wire compatibility:** response stored in Lekh / outbox must still expose:

- `actions`
- `blocking_rule_id` when `BLOCK` (first deny-driving `rule_hits[0]` or `"decision_api_deny"` if empty)
- `evaluation_trace` (minimal): `{ "source": "decision_api", "trace_id", "decision", "score", "rule_hits", "action_map": "action_map_v1" }`

Config knobs (env):

- `DECISION_API_URL` (replaces evaluate use of `RULE_ENGINE_URL`)
- `ORCHESTRATOR_ACTION_MAP_VERSION=action_map_v1`
- Optional thresholds are **not** re-implemented in orchestrator — trust decision-api’s deny/review thresholds.

---

## 6. Cutover plan

### Phase 0 — Bridge behind flag ✅ (2026-07-11)

- `RULE_EVAL_BACKEND=python|decision_api` (Phase 2 default: `decision_api`).
- `decision_evaluate_bridge.py`: map + HTTP client + `action_map_v1`; fail-closed tenant.
- Unit + ingest gate tests green.

### Phase 1 — Shadow traffic ✅ (2026-07-12)

- Staging: set `RULE_EVAL_BACKEND=decision_api` + `DECISION_API_URL`.
- Optional dual-run: `RULE_EVAL_DUAL_RUN=true` calls Python + decision-api, logs
  `orchestrator_rule_eval_dual_run` diffs (`actions`, `blocking_rule_id`); **side effects
  always from decision-api**. Python secondary failures are best-effort (warn, continue).
- Compose comments + `.env.example` document the knobs.

### Phase 2 — Default flip ✅ (2026-07-13)

- Code default `RULE_EVAL_BACKEND=decision_api` (falls back to `python` if `DECISION_API_URL` unset).
- `docker-compose.v2-ingest.yml`: `decision-api` (sqlite) + orchestrator with
  `RULE_EVAL_BACKEND=decision_api` / `DECISION_API_URL=http://decision-api:8000`.
- Python sidecar kept behind compose profile `legacy-python-rules` for dual-run / rollback.

### Phase 3 — Delete Python evaluate path ✅ (2026-07-13)

- Default compose no longer starts `:8778` (profile only).
- `services/rule_engine/DEPRECATED.md` — HTTP evaluate archived; keep package for in-process AST
  (`rule_shadow_test`, `rules_import`, pack validators).
- Hypothesis promote + Versioned Rule Control **removed** (AST UI deleted; packs via decision-api GitOps).
- Orchestrator `/health/full` probes `decision_api` when configured; skips Python probe when
  backend is `decision_api` (unless dual-run).

### Phase 4 — Declutter (P0/P1 + P2 ops done)

Completed:
1. Migrated CI off `legacy_v1_decision_api` and deleted the fork (rules/alembic owned by decision-api)
2. Case-rail copilot → investigation-agent (tools/shadow proxy local-only)
3. `tarka_v2_ui` marked DEPRECATED; pillars point at `frontend/`
4. Collapsed `graph-service` dual tree to `src/graph_service/`
5. Unified `MinuteRateLimiter` in `services/shared/minute_rate_limit.py`
6. Documented OpenSanctions ingress vs decision-api plugin boundary
7. **Calibration owner:** signal-api `/calibration` (`CALIBRATION_SERVICE_URL`); standalone
   Helm `calibrationService.enabled: false` + `services/calibration-service/DEPRECATED.md`
8. **Helm canonical:** `infra/deploy/helm/fraud-stack/` only (removed duplicate `helm/tarka/` + `fraud-stack-lite/`)
9. **Product cleanup:** deleted `tarka_v2_ui/`; removed Versioned Rule Control UI + `/api/rule-engine` proxy;
   `core_v2` marked DEPRECATED (speed-layer duplicate of decision-api)

---

## 7. Success criteria

1. Orchestrator `/v1/ingest` with `RULE_EVAL_BACKEND=decision_api` produces Lekh rows with valid `blocking_rule_id` on BLOCK and Shadow triggers on review path.  
2. No call to `RULE_ENGINE_URL/v1/evaluate` in that mode.  
3. Unit tests for `map_tx_to_evaluate_request` and `map_evaluate_to_actions`.  
4. At least one integration test: mock decision-api evaluate → ingest → actions.  
5. Documented rollback: set `RULE_EVAL_BACKEND=python`.

---

## 8. Risks

| Risk | Mitigation |
|------|------------|
| Action semantics differ from Python AST priority/short-circuit | Dual-run diff logs; tune packs/thresholds, not reintroduce AST |
| Missing features vs Python Neo4j field | Rely on decision-api graph path; fail-open same as today |
| AST UI / `fraud_rules` versioning breaks | Explicit deprecation or migrate to pack GitOps in Phase 3 |
| Latency | decision-api evaluate may be heavier than lightweight AST; measure p95 on ingest |

---

## 9. Open questions — resolved (2026-07-11)

### 9.1 Default `tenant_id` / `event_type` when metadata omits them?

**When does omission happen?** Often. `TransactionSchema` does **not** require `tenant_id` or `event_type` at the top level — only `entity_id`, `amount`, `timestamp`, plus optional `metadata` / `country`. Producers that only send the payment envelope will omit both unless they nest them under `metadata`.

**Resolution — fail closed on tenant; narrow default on event_type:**

| Field | Policy |
|-------|--------|
| `tenant_id` | **Required.** Resolve from (1) `metadata.tenant_id`, else (2) trusted header `X-Tenant-Id` if ingress already authenticated it. If still missing → **422** and do not call decision-api. No `collab_default` / `demo` invent for production ingest. |
| `event_type` | If missing, default to **`payment`** on the transaction ingest path (the envelope is a payment/tx). Allow override via `metadata.event_type` when present and valid (`EventType` enum). |

Rationale: processing without a tenant is multi-tenant CTI / data-mixing risk, not “helpful defaulting.” Event type is a scoring facet; `payment` is the honest default for `/v1/ingest` transactions.

### 9.2 Does hypothesis promote need a successor before Python sidecar removal?

**What it is today:** Analyst promotes a Shadow-suggested rule AST → `tarka_v2_ui` BFF `POST /api/v1/hypotheses/promote` → Python `RULE_ENGINE_URL/v1/rules/deploy` → append/activate row in Postgres `fraud_rules` (+ promotion_feedback). Related surfaces: frontend `ruleEngine.listVersions` / rollback via `/api/rule-engine/…`, and `POST /v1/hypotheses/deploy` (Redis + NATS for the Rust *watcher* shadow ruleset — different from evaluate).

**Can it wait?** **Yes, for Phase 0–2 cutover of evaluate**, if product accepts: promote / AST version UI returns **410/503** (or stays on a temporary Python admin-only deploy) until pack GitOps is the promote path.

**Must not wait (before Phase 3 delete)** if any production workflow still:

- promotes hypotheses into live `fraud_rules`, or  
- depends on `/v1/rules/versions` rollback for production AST rulesets.

**Successor (when needed):** write promoted rules as decision-api JSON packs (GitOps / `RULES_PATH` reload) or a decision-api “rule pack deploy” API — not a second evaluate engine. Shadow Redis/NATS hypothesis deploy can stay on the watcher path independently of Python HTTP evaluate.

### 9.3 core-api mount prefix — evaluate URL?

**Yes.** `core-api` does `app.mount("/decisions", dec.app)`. Decision-api route is `POST /v1/decisions/evaluate`. Full URL:

```text
http://core-api:8000/decisions/v1/decisions/evaluate
```

Helm already sets `DECISION_API_URL` / `decisionApiUrl` to the **mount base** `http://…-core-api:8000/decisions` (not including `/v1/decisions/evaluate`). Orchestrator bridge must:

```text
DECISION_API_URL = http://core-api:8000/decisions   # base
POST {DECISION_API_URL}/v1/decisions/evaluate
```

Standalone decision-api (no mount) uses `http://decision-api:8000/v1/decisions/evaluate` with `DECISION_API_URL=http://decision-api:8000`. Confirmed by `demo_burst.py` (`/decisions/v1/decisions/evaluate`) and Helm values.

---

## 10. Approval

Design executed through Phase 3 evaluate cutover and Phase 4 P2 ops
(calibration owner + Helm canonical chart, 2026-07-13).
