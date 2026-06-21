# Q1/Q2 Epic closure evidence (June 2026)

Umbrella epics **#127–#142** closed after Q1/Q2 Epic Closure Plan delivery on `master`.

**Quarter gates satisfied:** Trust (E01, E02), Reliability (E03, E04, E08), Compliance (E06).

---

## Q1-E04 [#130] — SLO burn operationalization

- `infra/deploy/observability/prometheus-rules/slo-burn.yml` — `runbook_url` annotations, tier labels, platform-core service coverage
- `docs/docs/operations/slo-burn-response.md` — burn response runbook
- `docs/docs/guides/service-slos-v1.md` — Alertmanager routing + on-call mapping
- CI: Prometheus rules lint in `.github/workflows/ci.yml`

## Q1-E08 [#134] — Runbook pack

- `docs/docs/operations/runbook-pack-index.md` — unified index
- Cross-links from `infra/deploy/observability/grafana/provisioning/dashboards/json/tarka-slo-burn.json`

## Q1-E07 [#133] — Environment parity

- `infra/scripts/deploy/validate_env_contract.py` — env key contract gate
- CI: `Validate deployment env contract`, `tarka-deploy-settings schema gate` in `.github/workflows/ci.yml`

## Q1-E03 [#129] — Preset promotion

- `infra/scripts/deploy/promote_preset.sh`, `docs/docs/guides/staging-promotion-playbook.md`
- Helm template parity: `infra/deploy/helm/fraud-stack/templates/{calibration-service,counter-service,location-service,collaboration-chat-bridge}.yaml`

## Q1-E02 [#128] — Tenant binding

- `services/shared/auth.py`, `services/shared/tests/test_auth.py`
- `scripts/security/tenant_binding_smoke.py`
- CI: `test-shared-auth` matrix (`TENANT_BINDING_REQUIRED=true/false`)
- `infra/deploy/helm/fraud-stack/presets/tenant-binding-enforced.yaml`

## Q1-E01 [#127] — Policy-as-code

- `infra/scripts/policy/validate_opa_bundle.py`, `infra/scripts/policy/validate_deployment_profile_manifest.py`
- `infra/deploy/profiles/default-deployment-profile.yaml`
- Extended `infra/scripts/policy/validate_rule_packs.py` for v2 rule-engine packs

## Q1-E05 [#131] — Degraded-mode UX

- `frontend/src/api/client.ts` — `toUserFacingApiError` / `ApiRequestError`
- `frontend/src/components/DegradedModeBanner.tsx` — Cases, CaseDetail, Rules, Investigation, Dashboard
- Vitest: `client.errors.test.ts`, `userFacingErrors.test.ts`, `DegradedModeBanner.test.tsx`

## Q1-E06 [#132] — Release governance

- `infra/deploy/release/governance-checklist.yaml`
- `scripts/release/validate_governance_checklist.py`
- CI: `Validate release governance checklist (Q1-E06)`

---

## Q2-E04 [#138] — Entity resolution (backend + UI)

- `migrations/20260603_002_macro_seasonal_baselines.sql`, `scripts/apply_clickhouse_migration.py`
- Orchestrator HIL overrides: `services/orchestrator/src/orchestrator/routes/hil_overrides.py`
- Resolution confidence: `entity_profile.py`, `entity_resolution.py`
- UI: `frontend/src/components/CaseView/workbench/panels/HilOverridePanel.tsx`

## Q2-E02 [#136] — Copilot citations

- `services/investigation-agent/src/investigation_agent/citation_schema.py`
- Analytics persistence: `copilot_analytics.py`
- Safe-action gate + CI golden eval: `test_copilot_eval_golden.py` in `test-investigation-agent`

## Q2-E03 [#137] — Graph path reasoning

- `services/graph-service/src/graph_service/path_explain.py`
- Case-api annotations: `services/case-api/src/case_api/graph_case_api.py`
- UI: `frontend/src/components/CaseView/workbench/panels/PathReasoningPanel.tsx`

## Q2-E05 [#139] — Drift and benchmark

- `services/decision-api/src/decision_api/benchmark_export_api.py`, `drift_query_api.py`
- Scorecard: `docs/docs/releases/evidence/v1.2.0-vertical-benchmark-scorecard.json`
- UI: `frontend/src/components/CaseView/workbench/panels/BenchmarkDriftTiles.tsx`

## Q2-E06 [#140] — Counter catalog

- `services/decision-api/src/decision_api/internal_counters_api.py` — manifest version, parity metadata, replay jobs
- UI: `frontend/src/components/CaseView/workbench/panels/CounterTransparencyStrip.tsx`

## Q2-E08 [#142] — Collaboration bridge

- `services/collaboration-chat-bridge/` — case actions, thread correlation, outbound webhook schema
- CI: `test-collaboration-chat-bridge`
- UI: `frontend/src/components/CaseView/workbench/panels/BridgeConfirmDialog.tsx`

## Q2-E07 [#141] — Cross-workflow navigation

- `frontend/src/context/AnalystWorkspaceContext.tsx` — workbench commands, case tab hrefs
- `frontend/src/components/CommandPalette.tsx`, `AnalystCaseTabBar.tsx` — URL-sync tabs

## Q2-E01 [#135] — Unified workbench (closes last)

- `frontend/src/workbench/workbenchContract.ts`, `CaseWorkbenchContext.tsx`, `AnalystWorkbenchLayout.tsx`
- `frontend/src/pages/CaseDetail.tsx` — composable workbench shell + embedded copilot rail
- Telemetry: `frontend/src/workbench/workbenchTelemetry.ts`
