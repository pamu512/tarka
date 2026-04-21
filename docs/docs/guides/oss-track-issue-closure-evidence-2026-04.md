# OSS track (#31–#54): closure evidence and sprawl reduction

Use this as a **single checklist** when closing GitHub issues and duplicate PRs. Source DAG: [oss-ship-order-dependencies.md](./oss-ship-order-dependencies.md).

**Convention:** *Merged* = on default line (`ide/v1.2.5-7320` / `master` as applicable). *Open PR* = merge that PR then close the issue with the merge SHA.

---

## Work focus: open GitHub issues (prioritized queue)

Live list: [issues: open + `roadmap`](https://github.com/pamu512/tarka/issues?q=is%3Aissue+is%3Aopen+label%3Aroadmap). **Do not duplicate** work covered by [recently closed — evidence audit](#recently-closed--evidence-audit-2026-04-22) unless a gap is explicitly listed there.

**OSS P0/P1 quartet** ([#36](https://github.com/pamu512/tarka/issues/36), [#40](https://github.com/pamu512/tarka/issues/40), [#46](https://github.com/pamu512/tarka/issues/46), [#48](https://github.com/pamu512/tarka/issues/48)): **closed on GitHub** with evidence comments (2026-04-21). Default-line merge tracking: branch `feature/bridge-correlation-traceability` @ `2c6518cff845ae27f11439a6288f486cafc08900` until merged to `master`.

| Priority | Issue | Title (short) | In-repo notes |
|----------|-------|-----------------|---------------|
| P2 | [#55](https://github.com/pamu512/tarka/issues/55) … [#69](https://github.com/pamu512/tarka/issues/69) | Top-5 epics (Marble → xFraud) | **Next:** [#56](https://github.com/pamu512/tarka/issues/56) (template packs — `playbook_id` on case create shipped; CRUD + SLA fields remain). Then [#57](https://github.com/pamu512/tarka/issues/57)–[#69](https://github.com/pamu512/tarka/issues/69) per epic order below. |

### Next open issues — execution order

1. **Marble / investigation** — [#56](https://github.com/pamu512/tarka/issues/56) (finish template AC: CRUD, SLA/owner, workflow tests) → [#57](https://github.com/pamu512/tarka/issues/57) → epic [#55](https://github.com/pamu512/tarka/issues/55) when children done.
2. **RefundSwatterLite** [#58](https://github.com/pamu512/tarka/issues/58)–[#60](https://github.com/pamu512/tarka/issues/60) → **Chitragupta** [#61](https://github.com/pamu512/tarka/issues/61)–[#63](https://github.com/pamu512/tarka/issues/63) → **DGFraud** [#64](https://github.com/pamu512/tarka/issues/64)–[#66](https://github.com/pamu512/tarka/issues/66) → **xFraud** [#67](https://github.com/pamu512/tarka/issues/67)–[#69](https://github.com/pamu512/tarka/issues/69).

### Recently closed — evidence audit (2026-04-22)

| Issue | Closure vs repo | Evidence | Known gaps |
|-------|-----------------|----------|------------|
| [#52](https://github.com/pamu512/tarka/issues/52) | **Aligned** | `services/ml-scoring/rules/ml_promotion_policy_v1.{json,yaml}`; `scripts/ml/validate_ml_promotion_policy.py`, `check_ml_promotion_policy_sync.py`; `.github/workflows/ci.yml` ML promotion step; `services/ml-scoring/tests/test_model_registry.py`; `GET /v1/promotion-policy`. | None blocking; keep CI green on policy edits. |
| [#37](https://github.com/pamu512/tarka/issues/37) | **Mostly aligned** | `PROMOTION_GATE_ENFORCE`, `GET /v1/models/{name}/{version}/promotion-check` (`report`), activate/traffic-split gate + optional `x-ml-promotion-override`; `docs/docs/api-reference.md` ML scoring section. | **Process:** automated “link report into release notes” is not in-repo; operators attach `report` from promotion-check or 409 responses manually. |
| [#51](https://github.com/pamu512/tarka/issues/51) | **Partial vs issue template** | `frontend/src/components/AnalystReadinessBar.tsx`, `App.tsx`, Help `#readiness`; decision-api posture + SLO for banner data. | GitHub issue left **all AC checkboxes unchecked** at close; **no dedicated frontend automated tests** were cited at audit time. **Update:** **#36** now tracks Vitest coverage in `frontend/src/components/AnalystReadinessBar.test.tsx` (mocked `evaluationPosture` + `slo`). Remaining gap is optional full-browser E2E + template hygiene on GitHub. |
| [#36](https://github.com/pamu512/tarka/issues/36) | **Closed (GitHub 2026-04-21)** | Trust/ops readiness UX + Vitest `AnalystReadinessBar.test.tsx`; decision-api posture + SLO. | Follow optional Playwright / copy review off-issue if desired. |
| [#40](https://github.com/pamu512/tarka/issues/40) | **Closed (GitHub 2026-04-21)** | `POST /v1/evidence/summary` + goldens + allowlist; OpenAPI + UI. | — |
| [#46](https://github.com/pamu512/tarka/issues/46) | **Closed (GitHub 2026-04-21)** | Typology DSL + predicate registry + `validate_typology_dsl.py` CI. | — |
| [#48](https://github.com/pamu512/tarka/issues/48) | **Closed (GitHub 2026-04-21)** | `POST /v1/internal/parity/verify` + tests + OpenAPI. | — |

---

## Tier 0 — Client + environment baselines


| Issue   | Title (short)                         | Status                                                              | Evidence                                                                                                                                                                                                    |
| ------- | ------------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#43** | Python SDK resilient envelope         | **Merged PR #90 area + PR #91/#92** — confirm on branch after merge | `packages/fraud-sdk-python`: `envelope.py`, `evaluate_response.py`, `client.py` kwargs; `docs/docs/sdks/python.md`; tests `test_envelope.py`, `test_decision_client_evaluate.py`; `pytest.ini` `pythonpath` |
| **#44** | TypeScript runtime guards / fail-open | **PR #92** (combined with #43) or standalone branch                 | `packages/fraud-sdk-typescript/src/runtime.ts`, `DeviceSignalCollector` timeouts, `vitest`, `docs/docs/sdks/typescript.md`                                                                                  |
| **#45** | Mobile attestation taxonomy           | **Merged**                                                          | PR **#90** merge commit `**3e12842`**: `attestation_taxonomy.py`, `schemas.py`, `main.py` tags + governance, `mobile-attestation-taxonomy.md`, Android/iOS SDK + OpenAPI                                    |
| **#38** | Community vs Pro deployment docs      | **PR #93**                                                          | `docs/docs/guides/deployment-profiles-community-vs-pro.md`, `deploy/env/*.env.example`, links from `deploy/.env.example` + `docs/docs/index.md`                                                             |


---

## Tier 1 — Step contract


| Issue   | Title                  | Status                                                                  | Evidence                                                                                                                                                                                                                                                                       |
| ------- | ---------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **#32** | Pipeline step controls | **PR #94** → `ide/v1.2.5-7320` (branch `ide/github-32-eval-steps-7320`) | `eval_steps.py`, `config.py` `EVAL_STEP_*`, `main.py` list/graph_risk/feature/opa/ml steps + `step_trace` in audit, `_graph_upsert_stepped`, `opa_client.py` timeout param, `evaluation-step-controls.md`, `tests/test_eval_steps.py`, Prometheus counters `tarka_eval_step_*` |


---

## Tier 2 — Parallel cores


| Issue   | Title                          | Status                                              | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------- | ------------------------------ | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#31** | Policy DAG shadow / CC routing | **Partial — close when PR merges**                  | **Canary:** `json_rules` `canary_percent` + stable bucket (`_pack_experiment_bucket`). **Shadow:** `shadow.py` + NATS + `/v1/rules/shadow/`*. **CC (audit):** `POLICY_CHAMPION_CHALLENGER_ENABLED`, `payload_snapshot.policy_routing`, `evaluation_mode=challenger`. Doc: [policy-dag-oss-31.md](./policy-dag-oss-31.md).                                                                                                                                                                           |
| **#33** | Velocity counters + parity     | **Shippable** — close with merge SHA after PR lands | **Race / load:** `services/decision-api/tests/test_golden_counters.py` `TestConcurrentRecordEvents` (parallel `record_event`, assert count + `sum_amount_1h`). **Parity:** `scripts/replay/run_offline_parity.py`, `counter-parity-smoke.yml`, `test_golden_counters.py`. **Keys:** `counter_manifest_v1.json`, `normalized_velocity_key_names()` in `services/shared/fraud_aggregates.py`, `GET /v1/internal/counters/manifest`. **Docs:** [counter-replay-parity.md](./counter-replay-parity.md). |


---

## Tier 3 — First integrations


| Issue                              | Status                  | Notes                                                                                                                                                                                                                                   |
| ---------------------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#47** Canary cohort audit fields | **Ship when PR merges** | `payload_snapshot.canary_cohort` (`build_canary_cohort_audit`), `POLICY_COHORT_SALT`, `POLICY_EXPERIMENT_ID`; [policy-dag-oss-31.md](./policy-dag-oss-31.md)                                                                            |
| **#34** Typology layer             | **Ship when PR merges** | `typology_definitions_v1.json`, `decision_api/typology.py`, audit `payload_snapshot.typologies` + `typology_summary`; [oss-typology-parity-graph-34-48-49.md](./oss-typology-parity-graph-34-48-49.md)                                  |
| **#48** Parity verifier job        | **Ship when PR merges** | `POST /v1/internal/parity/verify` on feature-service; [oss-typology-parity-graph-34-48-49.md](./oss-typology-parity-graph-34-48-49.md)                                                                                                  |
| **#49** Graph checkpoint registry  | **Ship when PR merges** | `graph-service/rules/checkpoint_profiles_v1.json`, `GET /v1/checkpoint-profiles`, `entity-risk?checkpoint=`, decision-api `metadata.graph_checkpoint`; [oss-typology-parity-graph-34-48-49.md](./oss-typology-parity-graph-34-48-49.md) |


---

## Tier 4 — Product slices

| **#46–#50** (excl. closed **#37**, **#51**) | Partial | Evidence bundle v1 schema + investigation-agent `evidence_bundle_draft` v1/dual shipped; Case API `/v1/cases/{case_id}/evidence-bundle` now emits `evidence_bundle_v1` block aligned with `tarka-evidence-bundle-v1.schema.json`. **#37**/**#51** closed — see [audit](#recently-closed--evidence-audit-2026-04-22). Close **#46** when DSL AC met; avoid duplicate planning issues without PR linkage. |

---

## Tier 5 — Packaging + ops


| Issue                              | Status     | Evidence                                                                                                                           |
| ---------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **#39** Starter typology packs     | Partial    | Reference typologies (`velocity_abuse`, `new_payee_risk`, `amount_stress`) wired via `typology_definitions_v1.json` + DSL/registry; starter fixtures under `services/decision-api/tests/fixtures/typology_starter_events.json` with smoke test `test_starter_typology_fixtures_cover_reference_packs` exercising golden typology outcomes. |
| **#40** Investigation summaries    | Partial    | `POST /v1/evidence/summary` + tests (investigation-agent) — cite PR/commits for Epic F                                             |
| **#41** Automated scorecards       | Partial    | Integration scorecards + connector quality, plus analytics-sink `GET /v1/analytics/scorecard` (JSON decision scorecard with per-decision metrics and top rule hits) — not yet a full emitter/publisher framework. |
| **#42** Graph selective routing    | Partial    | `graph_routing_policy_v1.json` + `decide_graph_routing()` in decision-api (audit at `payload_snapshot.graph_routing`); tests `test_graph_routing_policy.py` — merged into `ide/v1.2.5-7320` |
| **#52** Promotion policy YAML + CI | **Closed (audited)** | `validate_ml_promotion_policy.py`, `check_ml_promotion_policy_sync.py`, CI step in `.github/workflows/ci.yml`; see [§ Recently closed](#recently-closed--evidence-audit-2026-04-22) |
| **#54** Connector quality + probes | **Merged** | PR **#90** / `**3e12842`**: `preflight-probes`, `connector_quality` v1, catalog swimlane, `integration_catalog.py`, OpenAPI, tests |


---

## First-class risk services (Cal/Counter/Location) — implementation evidence

| Issue / backlog anchor | Status | Evidence |
| --- | --- | --- |
| **#33** Counter parity + maturity | **Implementation landed (branch evidence pending merge SHA)** | New service + contract: `contracts/openapi/counter-service.yaml`, `services/counter-service/src/counter_service/main.py`, tests `services/counter-service/tests/test_main.py`. Decision runtime integration: `settings.counter_service_url` + circuit breaker + fallback tags in `services/decision-api/src/decision_api/main.py`. Frontend ops surface: `frontend/src/pages/OpsCounters.tsx`. |
| Location / co-location backlog (critical gap from scorecard review) | **Implementation landed (branch evidence pending merge SHA)** | New service + contract: `contracts/openapi/location-service.yaml`, `services/location-service/src/location_service/main.py`, tests `services/location-service/tests/test_main.py`. Decision runtime integration: `settings.location_service_url`, `location_eval` step + provenance in inference/audit. Graph semantics maintained through existing `Place`/`SEEN_AT` writes in `decision-api` graph upsert flow. |
| Calibration service-first runtime | **Implementation landed (branch evidence pending merge SHA)** | New service + contract: `contracts/openapi/calibration-service.yaml`, `services/calibration-service/src/calibration_service/main.py`, tests `services/calibration-service/tests/test_main.py`. Decision runtime integration: `settings.calibration_service_url`, calibration step + audit snapshot embedding (`payload_snapshot.calibration`). |
| Cross-service confidence provenance | **Implementation landed (branch evidence pending merge SHA)** | Inference context now carries first-class provenance fields: `calibration_profile_version`, `location_confidence`, `confidence_sources` in `services/decision-api/src/decision_api/inference_build.py` + `schemas.py`; OpenAPI contract updated in `contracts/openapi/decision-api.yaml`; frontend rendering in `frontend/src/pages/CaseDetail.tsx` and parser in `frontend/src/api/inferenceContext.ts`. |
| Runtime resilience + auth hardening | **Implementation landed (branch evidence pending merge SHA)** | Per-upstream circuits and fallback reasons (`circuit_calibration/counter/location`) in decision runtime; fail-closed shared auth in `services/shared/auth.py`, RBAC posture in `services/shared/auth_rbac.py`; SLO endpoints in each new service and burn-rate coverage extended in `deploy/observability/prometheus-rules/slo-burn.yml`, with scrape targets wired in `deploy/observability/prometheus.yml`. |

---

## Tier 6 — Publishing

| **#53** Scorecard → Discussions | Partial | Use analytics-sink `GET /v1/analytics/scorecard` as the machine-readable source of truth; remaining: wired weekly publisher to Discussions and UI surfaces. |

---

## Sprawl reduction actions

1. **Merge PR #92** (or #91 + #44 separately) then **close #43 and #44** with one comment pointing at the combined merge SHA.
2. **Merge PR #93** then **close #38** with `3eb2c37` (or updated tip).
3. **Merge PR #94** (#32) then **close #32** with the **merge commit SHA** on `ide/v1.2.5-7320` + link to `evaluation-step-controls.md`.
4. **Close #45 and #54** if not already: `**3e12842`** (PR #90).
5. **Supersede duplicate PRs**: if #92 contains #43, close **#91** as superseded.
6. **Epics #1–#12**: close only when acceptance tests + merge SHAs documented (many items already landed on `ide/v1.2.5-7320` — use git log and issue AC).

---

*Last updated: 2026-04-22 — open queue + closed-issue evidence audit tightened; refresh SHAs after each merge to `ide/v1.2.5-7320` / `master`.*