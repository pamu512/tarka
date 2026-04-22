# Tarka 12-Month Roadmap Execution Kit

This execution kit operationalizes the approved aspirational roadmap into owner-tagged work, quarterly candidate epics, measurable KPIs, launch gates, and governance rhythm.

## GitHub tracking (umbrella epics)

The doc stays the narrative source of truth. **Umbrella epic issues** on GitHub are for assignment, discussion, and linking child issues. Each epic uses labels `roadmap`, `help wanted`, and one or more `area/`* tags. Use `**good first issue`** on small, scoped **child** issues only.

**Milestones:** [Q1-2026](https://github.com/pamu512/tarka/milestone/9) · [Q2-2026](https://github.com/pamu512/tarka/milestone/10) · [Q3-2026](https://github.com/pamu512/tarka/milestone/11) · [Q4-2026](https://github.com/pamu512/tarka/milestone/12)


| Epic ID | Umbrella issue                                      |
| ------- | --------------------------------------------------- |
| Q1-E01  | [#127](https://github.com/pamu512/tarka/issues/127) |
| Q1-E02  | [#128](https://github.com/pamu512/tarka/issues/128) |
| Q1-E03  | [#129](https://github.com/pamu512/tarka/issues/129) |
| Q1-E04  | [#130](https://github.com/pamu512/tarka/issues/130) |
| Q1-E05  | [#131](https://github.com/pamu512/tarka/issues/131) |
| Q1-E06  | [#132](https://github.com/pamu512/tarka/issues/132) |
| Q1-E07  | [#133](https://github.com/pamu512/tarka/issues/133) |
| Q1-E08  | [#134](https://github.com/pamu512/tarka/issues/134) |
| Q2-E01  | [#135](https://github.com/pamu512/tarka/issues/135) |
| Q2-E02  | [#136](https://github.com/pamu512/tarka/issues/136) |
| Q2-E03  | [#137](https://github.com/pamu512/tarka/issues/137) |
| Q2-E04  | [#138](https://github.com/pamu512/tarka/issues/138) |
| Q2-E05  | [#139](https://github.com/pamu512/tarka/issues/139) |
| Q2-E06  | [#140](https://github.com/pamu512/tarka/issues/140) |
| Q2-E07  | [#141](https://github.com/pamu512/tarka/issues/141) |
| Q2-E08  | [#142](https://github.com/pamu512/tarka/issues/142) |
| Q3-E01  | [#143](https://github.com/pamu512/tarka/issues/143) |
| Q3-E02  | [#144](https://github.com/pamu512/tarka/issues/144) |
| Q3-E03  | [#145](https://github.com/pamu512/tarka/issues/145) |
| Q3-E04  | [#146](https://github.com/pamu512/tarka/issues/146) |
| Q3-E05  | [#147](https://github.com/pamu512/tarka/issues/147) |
| Q3-E06  | [#148](https://github.com/pamu512/tarka/issues/148) |
| Q3-E07  | [#149](https://github.com/pamu512/tarka/issues/149) |
| Q4-E01  | [#150](https://github.com/pamu512/tarka/issues/150) |
| Q4-E02  | [#151](https://github.com/pamu512/tarka/issues/151) |
| Q4-E03  | [#152](https://github.com/pamu512/tarka/issues/152) |
| Q4-E04  | [#153](https://github.com/pamu512/tarka/issues/153) |
| Q4-E05  | [#154](https://github.com/pamu512/tarka/issues/154) |
| Q4-E06  | [#155](https://github.com/pamu512/tarka/issues/155) |
| Q4-E07  | [#156](https://github.com/pamu512/tarka/issues/156) |


To regenerate umbrella issues in a **fork** (avoid duplicate issues on the main repo), edit `REPO` in `[scripts/github/create_roadmap_epic_issues.py](../../../scripts/github/create_roadmap_epic_issues.py)` or create issues manually using the same title pattern: `[Roadmap] Qx-Enn: …`.

## Q1 Dependency Codification (in-flight work -> explicit owners)


| ID     | Work item                               | Source paths                                                                                                                                                                             | Primary owner           | Supporting owners                          | Exit criterion                                                                                       |
| ------ | --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| Q1-D01 | Cloud preset promotion baseline         | `.github/workflows/ci.yml`, `scripts/deploy/generate_cloud_values.py`, `scripts/ci/cloud_preset_smoke.py`, `deploy/helm/fraud-stack/presets/*.yaml`                                      | Platform Engineering    | SRE, QA                                    | Preset generation and validation pass in CI and are consumed by staging release playbooks.           |
| Q1-D02 | Helm service surface contract hardening | `deploy/helm/fraud-stack/templates/{calibration-service,counter-service,location-service,opa,collaboration-chat-bridge,workload-operations}.yaml`, `deploy/helm/fraud-stack/values.yaml` | Platform Engineering    | Service Owners                             | Enabled chart profiles render with complete env/dependency contracts and no template drift.          |
| Q1-D03 | Tenant-aware auth enforcement baseline  | `services/shared/tenant_binding.py`, `services/shared/auth.py`, `services/shared/auth_rbac.py`, `services/shared/tests/test_auth.py`                                                     | Security Engineering    | API Service Owners                         | Tenant binding is enforceable by policy flags and auth regression suite passes for protected routes. |
| Q1-D04 | Release-readiness policy uplift         | `docs/docs/guides/deployment-release-readiness.md`, `docs/docs/guides/deployment-presets.md`, `docs/docs/guides/deployment-aws.md`, `docs/docs/guides/deployment-gcp.md`                 | Product Operations      | Platform Engineering, Security Engineering | Hosted and self-hosted release checklists have pass/fail gates and named sign-off owners.            |
| Q1-D05 | SLO burn coverage expansion             | `deploy/observability/prometheus-rules/slo-burn.yml`                                                                                                                                     | SRE                     | Service Owners                             | Burn-rate rules include new risk services with runbook links and severity mapping.                   |
| Q1-D06 | Analyst trust-facing UX baseline        | `frontend/src/utils/userFacingErrors.ts`, `frontend/src/pages/{Cases,CaseDetail,Investigation,Rules}.tsx`, `frontend/src/api/client.ts`                                                  | Frontend Engineering    | Product Design, Case Ops                   | User-facing failure states are actionable and consistent across analyst workflows.                   |
| Q1-D07 | Production-hardening env parity         | `deploy/.env.example`, `deploy/docker-compose.yml`, `deploy/docker-compose.production-hardening.yml`, `deploy/hosted/k8s/overlays/*/kustomization.yaml`                                  | DevEx                   | Platform Engineering, Security Engineering | Environment contracts are aligned across local, hosted-k8s, and production-hardening paths.          |
| Q1-D08 | Cloud-native docs bundle finalization   | `docs/docs/guides/deployment-cloud-native-bundles.md`, `docs/docs/guides/deployment-managed-services.md`, `docs/docs/guides/deployment-lighter-runtime.md`                               | Technical Documentation | Product Operations                         | Docs include decision tree for profile selection and escalation path for misconfiguration.           |


## Quarterly Backlog (6-10 candidate epics each)

Sizing key: `S` (1-2 sprints), `M` (2-4 sprints), `L` (4-8 sprints).
Dependency tags: `SEC`, `PLAT`, `DATA`, `UX`, `GRAPH`, `AI`, `SRE`, `COMP`.

### Q1 (Months 1-3): Trust Foundation and Hardening


| Epic ID | Epic                                                  | Size | Dependency tags |
| ------- | ----------------------------------------------------- | ---- | --------------- |
| Q1-E01  | Policy-as-code baseline for default deployments       | M    | SEC, PLAT, COMP |
| Q1-E02  | Tenant binding enforcement rollout and migration aids | M    | SEC, DATA       |
| Q1-E03  | Preset and overlay promotion framework                | M    | PLAT, SRE       |
| Q1-E04  | Service health/SLO burn operationalization            | S    | SRE, PLAT       |
| Q1-E05  | Analyst error and degraded-mode UX baseline           | M    | UX, AI          |
| Q1-E06  | Release-readiness sign-off automation                 | S    | COMP, SRE       |
| Q1-E07  | Environment parity and config contract tests          | M    | PLAT, SEC       |
| Q1-E08  | Runbook pack for fallback and emergency ops           | S    | SRE, COMP       |


### Q2 (Months 4-6): Analyst, Graph, and Copilot Scale


| Epic ID | Epic                                                   | Size | Dependency tags |
| ------- | ------------------------------------------------------ | ---- | --------------- |
| Q2-E01  | Unified analyst workbench composition                  | L    | UX, AI, GRAPH   |
| Q2-E02  | Copilot confidence and citation quality framework      | M    | AI, COMP        |
| Q2-E03  | Graph explainability and path reasoning surfaces       | M    | GRAPH, UX       |
| Q2-E04  | Entity resolution confidence and analyst override loop | M    | GRAPH, DATA     |
| Q2-E05  | Drift and benchmark analytics dashboards               | M    | DATA, AI, SRE   |
| Q2-E06  | Counter catalog and operator transparency API/UI       | S    | DATA, UX        |
| Q2-E07  | Cross-workflow navigation and state continuity         | S    | UX              |
| Q2-E08  | Collaboration bridge bidirectional case actions        | M    | AI, PLAT        |


### Q3 (Months 7-9): Governance, Reliability, and MLOps Depth


| Epic ID | Epic                                                  | Size | Dependency tags |
| ------- | ----------------------------------------------------- | ---- | --------------- |
| Q3-E01  | Rule/model/policy bundle promotion workflow           | L    | DATA, COMP, SEC |
| Q3-E02  | Offline-online parity and lineage registry            | L    | DATA, AI        |
| Q3-E03  | Queue backpressure and ingest resiliency suite        | M    | SRE, PLAT       |
| Q3-E04  | DR rehearsal automation and scorecards                | M    | SRE, COMP       |
| Q3-E05  | Compliance evidence auto-pack generation              | M    | COMP, SEC       |
| Q3-E06  | Experiment governance (holdout, sample-size warnings) | M    | DATA, AI        |
| Q3-E07  | Secrets rotation and service identity hardening       | M    | SEC, PLAT       |


### Q4 (Months 10-12): Productization and Ecosystem


| Epic ID | Epic                                                       | Size | Dependency tags |
| ------- | ---------------------------------------------------------- | ---- | --------------- |
| Q4-E01  | Progressive delivery (canary/blue-green) toolkit           | L    | PLAT, SRE       |
| Q4-E02  | Connector SDK and partner certification profile            | M    | PLAT, DATA      |
| Q4-E03  | External evidence ingestion normalization                  | M    | DATA, COMP      |
| Q4-E04  | Executive trust and compliance analytics pack              | M    | DATA, UX        |
| Q4-E05  | Copilot persona and policy-controlled action framework     | M    | AI, SEC         |
| Q4-E06  | Tenant-safe benchmarking and cohort exports                | M    | DATA, COMP      |
| Q4-E07  | Flight-recorder diagnostics for hosted/self-hosted support | S    | SRE, PLAT       |


## Category KPI Matrix + Instrumentation Requirements


| Category               | KPI (target intent)                                                                    | Instrumentation requirement                                                         |
| ---------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Security               | Policy coverage ratio, tenant auth denial precision, key rotation success rate         | Structured auth decision logs; policy evaluation counters; rotation job audit trail |
| Compliance             | Evidence completeness index, control drift MTTR, audit prep lead time                  | Control-state event schema; signed evidence metadata; release checklist telemetry   |
| AI-Copilot             | Citation validity rate, analyst acceptance rate, unsafe action block rate              | Prompt/response trace IDs; citation verifier outcomes; HITL action audit events     |
| Analytics              | Dashboard adoption, drift detection lead time, data freshness SLA                      | Query audit logs; drift detector events; freshness lag metrics from sinks/pipelines |
| UI/UX                  | Task completion time, degraded-mode recovery success, error comprehension score        | Frontend interaction analytics; error taxonomy tags; post-action feedback events    |
| Graph/Entity           | Explainability usage, entity resolution confidence calibration, ring detection utility | Graph query traces; confidence distribution logs; analyst feedback labels           |
| Platform/Deployment    | Deploy success rate, rollback frequency, environment conformance score                 | CI/CD deployment events; preset/overlay conformance checks; release gate outputs    |
| Reliability/SRE        | SLO attainment, burn alert fatigue ratio, recovery time                                | Golden signal metrics; burn alert annotations; incident timeline ingestion          |
| Data Governance/MLOps  | Lineage completeness, parity failure rate, experiment governance compliance            | Feature/model lineage store; parity batch reports; experiment registry validation   |
| Integrations/Ecosystem | Connector reliability SLA, contract compatibility pass rate, integration MTTR          | Integration health pings; contract test results; incident-tagged connector events   |


## Quarter Gate Criteria (Go/No-Go)

### Trust gate (security + data trust)

- `GO` only if policy checks pass for default deployment profile, tenant enforcement regression passes, and evidence-signing/immutability controls are enabled for targeted workloads.
- `NO-GO` on unresolved critical auth bypass, unknown tenant scope behavior, or unowned secrets rotation gaps.

### Reliability gate (operational readiness)

- `GO` only if SLO burn alerts are wired to active runbooks, DR rehearsal for scoped services has a passing report, and queue/backpressure tests pass.
- `NO-GO` on unbounded backlog growth, untested recovery paths, or no rollback runbook for changed critical services.

### Compliance-sensitive launch gate

- `GO` only if control evidence pack is generated for release scope, release checklist has required owner signatures, and regional data handling profile is explicitly declared.
- `NO-GO` on missing evidence artifacts, ambiguous data residency behavior, or unresolved high-severity compliance control drift.

## Governance Cadence and Backlog Rebalancing

### Monthly governance structure


| Week   | Forum                                | Scope                                                  | Participants                          | Mandatory artifacts                        |
| ------ | ------------------------------------ | ------------------------------------------------------ | ------------------------------------- | ------------------------------------------ |
| Week 1 | Architecture and Security Council    | Cross-category dependency review, trust-risk decisions | Eng Leads, Security, Platform, SRE    | Dependency risk register, decision log     |
| Week 2 | Product and UX Delivery Review       | Analyst and copilot roadmap validation                 | Product, Frontend, AI, Case Ops       | Epic health board, UX risk notes           |
| Week 3 | Reliability and Compliance Readiness | SLO, DR, evidence readiness                            | SRE, Compliance, Security, Platform   | SLO report, DR status, evidence pack score |
| Week 4 | Portfolio Rebalance Session          | Capacity shifts between hosted and self-hosted tracks  | PMO, Engineering Managers, Tech Leads | Rebalanced epic slate, staffing changes    |


### Rebalancing rules

1. Keep a `60/40` capacity split as default: `60` for trust/reliability/platform, `40` for net-new product features.
2. If trust or reliability gates fail in a quarter, shift the next month to `75/25` until gate health is restored.
3. Hosted and self-hosted tracks both require at least one milestone epic each quarter.
4. Any new `L` sized epic requires one `S` or `M` de-risking predecessor to be in progress first.
5. No more than two concurrent `L` epics across the whole portfolio.

### Operational artifacts to maintain

- Quarterly epic board with tags (`SEC`, `PLAT`, `DATA`, `UX`, `GRAPH`, `AI`, `SRE`, `COMP`).
- Risk register linked to trust/reliability/compliance gates.
- KPI scorecard snapshot published monthly.
- Hosted vs self-hosted milestone parity tracker.

## Suggested Ownership Roster (role-based)

- Security Engineering: policy-as-code, auth boundary, secrets, evidence integrity.
- Platform Engineering: Helm/presets/overlays, deployment contracts, release automation.
- SRE: SLOs, alerts, incident/runbook quality, DR rehearsals.
- Data and ML Engineering: lineage, drift, parity, experiment governance.
- Frontend and Product Design: analyst workbench, usability, failure-transparent UX.
- AI Systems: copilot confidence and safe-action workflows.
- Compliance and Product Operations: evidence packs, control mappings, launch sign-offs.