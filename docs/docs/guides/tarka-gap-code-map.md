# Tarka: competitive gap → codebase map

Maps the gaps described in [competitive-critical-review-2026-04.md](competitive-critical-review-2026-04.md) and [competitive-score-matrix-2026-04.md](competitive-score-matrix-2026-04.md) to **concrete services and files** in this repository. Use this for planning work; **not** committed automatically—review and commit when ready.

Legend: **Today** = where behavior exists now; **Extend** = natural place to deepen; **Missing** = no first-class module yet.

---

## 1. Inference normalization & confidence calibration

**Gap:** Heterogeneous signals need a single, calibrated trust contract across web/mobile/services (matrix: Tarka ~2.5 vs leaders ~4–4.5).

| Role | Path |
|------|------|
| **Today — heuristic `inference_context`** | `services/decision-api/src/decision_api/main.py` — `build_inference_context()`, tag→risk heuristics, `integrity_confidence` blend |
| **Today — API contract** | `services/decision-api/src/decision_api/schemas.py` — response fields including `InferenceContext` |
| **Today — OpenAPI** | `contracts/openapi/decision-api.yaml` |
| **Today — shared JSON schema** | `contracts/json-schema/device-context.json`, `feature-snapshot.json`, `fraud-event.json` |
| **Today — SDK typing** | `packages/fraud-sdk-python/`, `packages/fraud-sdk-typescript/src/index.ts` |
| **Today — features fed into rules/ML** | `services/feature-service/` — snapshot API; `contracts/openapi/feature-service.yaml` |
| **Today — ML score input to inference** | `services/decision-api/src/decision_api/main.py` — `_fetch_ml_score`, `build_inference_context(..., ml_score, final_score)` |
| **Extend** | Same `main.py` + `feature-service` for **tiered confidence**, per-signal calibration, versioned schema |
| **Missing** | Cross-SDK **golden tests** / parity gates; production **calibration** pipeline (reliability diagrams, drift) |

---

## 2. Replay / tamper / MitM hardening

**Gap:** Production-grade ingress integrity vs advanced abuse (matrix ~2.5).

| Role | Path |
|------|------|
| **Today — payload replay signature** | `services/decision-api/src/decision_api/main.py` — `replay_signature`, `check_and_store_replay_signature` |
| **Today — Redis replay + nonces** | `services/decision-api/src/decision_api/redis_store.py` — `check_and_store_replay_signature`, `store_nonce` / `consume_nonce` |
| **Today — attestation endpoints** | `services/decision-api/src/decision_api/main.py` — `/v1/attestation/challenge`, `/v1/attestation/verify` |
| **Today — captcha verify helper** | `services/decision-api/src/decision_api/captcha.py` |
| **Today — device → tags (tamper/network/geo)** | `services/decision-api/src/decision_api/main.py` — `extract_device_signal_tags`, `extract_behavior_tags`, `extract_captcha_tags` |
| **Today — shared device fingerprint** | `services/decision-api/src/decision_api/fingerprint_store.py` |
| **Today — TS SDK attestation** | `packages/fraud-sdk-typescript/src/index.ts` — challenge / browser_challenge flow |
| **Tests** | `services/decision-api/tests/test_api_endpoints.py`, `test_signal_tags.py` |
| **Extend** | MitM / **certificate pinning** policy hooks; **Play Integrity / App Attest** paths beyond stubs; richer **tamper** taxonomy |
| **Missing** | Central **integrity policy** doc + enforced matrix (what counts as “high confidence” per platform) |

---

## 3. Counter / velocity platform maturity

**Gap:** Self-serve time windows, online/offline parity, replay in sim/shadow (matrix ~2.0).

| Role | Path |
|------|------|
| **Today — Redis sliding aggregates** | `services/decision-api/src/decision_api/aggregates.py` — `AggregateStore`, `count` / `sum_field` / `avg_field` / `distinct`, windows |
| **Today — wiring in decision path** | `services/decision-api/src/decision_api/main.py` — uses `agg_store` where configured |
| **Today — API rate limiting (HTTP)** | `services/shared/rate_limiter.py` — sliding window limiter middleware |
| **Today — velocity in ML** | `services/ml-scoring/` — features & tests referencing velocity (`test_scoring.py`, `explainability.py`) |
| **Today — vertical pack narratives** | `services/decision-api/src/decision_api/vertical_packs.py` — velocity-themed pack metadata |
| **Today — synthetic velocity in sim** | `services/decision-api/src/decision_api/simulator.py`, `simulation_api.py` |
| **Extend** | **Declarative counter definitions** (YAML/JSON), admin UI, **5m/1h/24h** presets, **replay** from audit stream |
| **Missing** | **Offline batch replay** job + parity checks vs online counters; counter **versioning** |

---

## 4. Location & co-presence coherence

**Gap:** Beyond basic geo mismatch tags (matrix ~1.5).

| Role | Path |
|------|------|
| **Today — geo tags → inference** | `services/decision-api/src/decision_api/main.py` — `geo_markers`, `geo_consistency_risk` inside `build_inference_context` |
| **Today — OSINT IP geo (ingress)** | `services/integration-ingress/src/integration_ingress/osint.py` — IP geolocation helpers |
| **Extend** | **Co-presence** (multi-device/session), **trusted location** enrollment, **impossible travel** with calibrated confidence |
| **Missing** | Dedicated **location service** or feature-service module; graph links for **session co-location** |

---

## 5. Analyst decision acceleration

**Gap:** Evidence summarization, benchmarks, workflow polish (matrix ~2.0).

| Role | Path |
|------|------|
| **Today — cases & comments** | `services/case-api/src/case_api/` — models, routes, workflows |
| **Today — case OpenAPI** | `contracts/openapi/case-api.yaml` |
| **Today — graph investigations** | `services/graph-service/` — subgraph, analytics endpoints; `contracts/openapi/graph-service.yaml` |
| **Today — LLM copilot** | `services/investigation-agent/` — chat + tools; `contracts/openapi/investigation-agent.yaml` |
| **Today — UI** | `frontend/src/pages/Cases.tsx`, `CaseDetail.tsx`, `GraphExplorer.tsx`, `Investigation.tsx` |
| **Extend** | **Top-driver explainability** panels wired to live `inference_context` + rule hit lineage; **queue KPIs** on case list |
| **Missing** | **Benchmark / cohort** overlays (“vs peer tenants”); **one-click evidence bundles** for SAR/disputes |

---

## 6. Rule operations & governance

**Gap:** Safer no-code rollout, telemetry on rule interactions, guardrails (matrix ~3.0 core, polish behind leaders).

| Role | Path |
|------|------|
| **Today — JSON rules engine** | `services/decision-api/src/decision_api/json_rules.py` |
| **Today — rule HTTP API** | `services/decision-api/src/decision_api/rule_api.py` |
| **Today — OPA** | `deploy/opa/policy.rego`; `services/decision-api` — `evaluate_opa` usage in `main.py` |
| **Today — shadow mode API** | `services/decision-api/src/decision_api/main.py` + rule packs — shadow observations/stats |
| **Today — simulation** | `services/decision-api/src/decision_api/simulation_api.py`, `simulator.py` |
| **Today — vertical packs** | `services/decision-api/src/decision_api/vertical_packs.py` |
| **Today — UI** | `frontend/src/pages/Rules.tsx`, `ShadowMode.tsx`, `Simulation.tsx` |
| **Extend** | **Rule change approvals**, canary % rollout, **per-rule contribution** metrics, **break-glass** audit |
| **Missing** | **Policy-as-code** CI gates (OPA + JSON schema) in default install path |

---

## 7. Challenge orchestration (step-up)

**Gap:** Low-friction-first challenge policies; FP friction if not tuned (P0 in critical review).

| Role | Path |
|------|------|
| **Today — attestation + nonce** | `services/decision-api/src/decision_api/main.py` — attestation routes; `redis_store.py` nonces |
| **Today — captcha integration** | `services/decision-api/src/decision_api/captcha.py` |
| **Today — UI mock actions** | `frontend/src/api/mockData.ts` — e.g. `recommended_action: "step_up_auth"` |
| **Missing** | **Orchestration service** or decision outcome → **action** mapping (SMS, WebAuthn, step-up URL); **policy templates** per risk tier |

---

## 8. Experiment guardrails (simulation / shadow)

**Gap:** Misleading A/B without standardized methodology (P0 in critical review).

| Role | Path |
|------|------|
| **Today — shadow observations** | `services/decision-api` — shadow endpoints in `main.py` / rule APIs |
| **Today — simulation & A/B** | `services/decision-api/src/decision_api/simulation_api.py` |
| **Today — UI** | `frontend/src/pages/ShadowMode.tsx`, `Simulation.tsx` |
| **Extend** | **Sample size / power** hints, **holdout** enforcement, **data leakage** checks between train/sim |
| **Missing** | **Experiment registry** (who ran what, when, on which population) |

---

## 9. Cross-cutting: observability & ops

| Role | Path |
|------|------|
| **Today — shared middleware** | `services/shared/observability.py`, `security_headers.py`, `auth_rbac.py` |
| **Today — analytics path** | `services/analytics-sink/` — ClickHouse sink + query API |
| **Today — streaming** | `services/event-ingest/` — NATS → decision |
| **Gap vs leaders** | **SLO dashboards**, **per-tenant** scorecard exports, **runbooks** in docs (some live under `docs/docs/guides/`) |

---

## 10. “Not in OSS scope” (no primary code target)

These gaps are **not** a missing folder—they are **business or data moats**:

- Proprietary **cross-merchant risk networks**
- **Chargeback guarantee** / insurance products
- **Managed SOC** / vendor-implemented SLAs
- **Licensed screening data** as a bundled SKU (you integrate via **integration-ingress** / adapters instead)

---

## Related internal docs

- [competitive-critical-review-2026-04.md](competitive-critical-review-2026-04.md)
- [competitive-score-matrix-2026-04.md](competitive-score-matrix-2026-04.md)
- [roadmap-30-60-90.md](roadmap-30-60-90.md) (if present)
- Module roadmaps: `docs/docs/projects/*-project.md`
