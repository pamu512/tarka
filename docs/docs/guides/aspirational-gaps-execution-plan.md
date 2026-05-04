# Aspirational gaps — execution plan

This document turns **“Missing”** and **large “Extend”** rows in [tarka-gap-code-map.md](./tarka-gap-code-map.md) into **sequenced work packages**. Each package lists **deliverables**, **primary code locations**, and **acceptance signals**. Order favors **dependencies** and **risk reduction** (contracts and tests before UI).

---

## Phase 1 — Contracts, calibration observability, and parity gates

**Goal:** Close the gap between “heuristic `inference_context`” and **operational calibration** without promising vendor-style reliability diagrams on day one.


| Step | Deliverable                                                                                                                        | Where                                                                                    | Acceptance                                                                    |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| 1.1  | **Cross-SDK golden vectors** for `device_context` + minimal evaluate payloads                                                      | `contracts/json-schema/`, `services/decision-api/tests/`, `packages/fraud-sdk-* / tests` | CI job fails if a canonical JSON fixture drifts from schema or server parsing |
| 1.2  | **Calibration / drift** already has `/v1/ops/calibration-status` — extend **docs + dashboards** linking drift to rule pack version | `docs/docs/guides/`, `deploy/observability/`                                             | Runbook: “when to bump calibration profile”                                   |
| 1.3  | **Reliability-style exports** (optional): export binned scores + labels to ClickHouse or CSV for offline reliability curves        | `analytics-sink` or batch script under `scripts/`                                        | Documented recipe, not a blocking product surface                             |


**Exit:** Scorecard can honestly say “calibration **observable** + **offline** analysis path”; full **automated** reliability diagrams remain Phase 2+ if product-prioritized.

---

## Phase 2 — Counters: versioning, offline parity, and operator UX

**Goal:** Make Redis aggregate keys and replay **first-class** for operators (already partially shipped: internal counters API, JSONL replay, CI parity smoke).


| Step | Deliverable                                                                                                               | Where                                                                   | Acceptance                                         |
| ---- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| 2.1  | **Counter versioning** policy in prod: `AGG_KEY_VERSION` migration runbooks (exists) + **automated** pre-flight in deploy | `docs/docs/guides/redis-agg-key-version-migration.md`, Helm/compose env | Staging checklist includes version bump drill      |
| 2.2  | **Offline batch replay** job: scheduled export from audit → replay → diff vs online sample                                | `scripts/replay/`, optional worker                                      | Diff report artifact in CI or nightly              |
| 2.3  | **Declarative counter catalog** UI or read-only API for non-engineers                                                     | `frontend/` or `GET` extension on internal counters                     | Analyst can see window definitions and key version |


---

## Phase 3 — Location and co-presence

**Goal:** Move from tags + graph primitives to **coherent** location features.


| Step | Deliverable                                                                                                                              | Where                                                                 | Acceptance                         |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------- |
| 3.1  | **Feature-service** module or documented subgraph for session **co-location** features (not a separate microservice required on day one) | `services/feature-service/`, `contracts/openapi/feature-service.yaml` | Contract tests + rule-pack example |
| 3.2  | **Graph** `SEEN_AT` / `Place` usage guides with **one** end-to-end demo script                                                           | `docs/docs/guides/examples/`, `scripts/`                              | Compose profile runs demo          |
| 3.3  | Optional **dedicated location service** only if latency/tenancy requirements exceed feature-service + graph                              | new `services/`                                                       | ADR documenting why split          |


---

## Phase 4 — Analyst acceleration and evidence

**Goal:** Benchmark overlays and exportable bundles for **SAR / disputes** workflows.


| Step | Deliverable                                                                                  | Where                                           | Acceptance                  |
| ---- | -------------------------------------------------------------------------------------------- | ----------------------------------------------- | --------------------------- |
| 4.1  | **Cohort / benchmark** compare API (tenant-scoped): e.g. score distribution vs baseline week | `case-api` or `analytics-sink` + decision audit | Permission model documented |
| 4.2  | **One-click evidence bundle**: zip/PDF of trace, rules, inference_context, graph slice       | `case-api` or investigation-agent export path   | E2E test with fixture case  |


---

## Phase 5 — Policy-as-code in the default path

**Goal:** OPA + JSON schema gates **on PR**, not only in advanced deployments.


| Step | Deliverable                                                                                              | Where                               | Acceptance                           |
| ---- | -------------------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------ |
| 5.1  | `**make policy-check`** (or GitHub Action) validating rule packs + OPA bundle against checked-in schemas | `.github/workflows/`, `deploy/opa/` | Required check on default branch     |
| 5.2  | **JSON Schema** for evaluate payload subsets versioned next to `contracts/json-schema/`                  | same                                | Breaking changes bump schema version |


---

## Phase 6 — Challenge orchestration and actions

**Goal:** Bridge `recommended_action` and policies to **executable** step-ups where appropriate.


| Step | Deliverable                                                                                                                    | Where                                    | Acceptance                  |
| ---- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- | --------------------------- |
| 6.1  | **Webhook / callback** template for step-up URL (tenant-configured)                                                            | `decision-api` or `integration-ingress`  | Signed callbacks documented |
| 6.2  | Optional **orchestration** microservice or worker: map outcome → SMS / email / WebAuthn session (provider-agnostic interfaces) | new small service or `services/worker-*` | Demo with mock provider     |


---

## Phase 7 — Experiment registry (depth)

**Goal:** Build on existing `**POST /v1/simulation/experiments`** + `experiment_registry.jsonl`.


| Step | Deliverable                                                                                 | Where                               | Acceptance                      |
| ---- | ------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------- |
| 7.1  | **GET** list/filter experiments (time range, type, population_id)                           | `experiment_api.py`                 | OpenAPI + tests                 |
| 7.2  | **Simulation UI** enforces **holdout** / sample-size warnings (extends “Extend” in gap map) | `frontend/src/pages/Simulation.tsx` | UX tests or manual QA checklist |


---

## Phase 8 — Integrity policy matrix (documentation + enforcement)

**Goal:** Single **matrix** doc: platform × signal × confidence tier, aligned with `integrity_policy.py` and attestation routes.


| Step | Deliverable                                                                         | Where      | Acceptance                                   |
| ---- | ----------------------------------------------------------------------------------- | ---------- | -------------------------------------------- |
| 8.1  | `**docs/docs/guides/integrity-confidence-matrix.md`**                               | docs       | Linked from decision-api README and SDK docs |
| 8.2  | Optional **CI** check: rule packs reference only **declared** attestation providers | `scripts/` | Non-blocking or warning initially            |


---

## Cross-cutting — SLOs and ops (ongoing)

- Per-tenant **scorecard export** JSON from `analytics-sink` or decision audit aggregates.
- Grafana panels for **evaluate latency**, **error budget**, and **replay** failures — extend `deploy/observability/`.

---

## Ordering summary

1. **Phase 1** (contracts + calibration path)
2. **Phase 2** (counters) — unblocks competitive “velocity platform” narrative
3. **Phase 5** (policy-as-code) — cheap security win in parallel with 2
4. **Phase 3** (location)
5. **Phase 7** (experiments depth)
6. **Phase 4** (analyst)
7. **Phase 6** (orchestration)
8. **Phase 8** (integrity matrix)

Adjust order if product prioritizes **analyst evidence (4)** over **location (3)** for a given release train.

---

## Related

- [Regulated markets feature pack](./feature-pack-regulated-markets.md) — optional checklist for fintech, banking, crypto-adjacent, and similar deployments (ingress, attestation, audit, data boundaries).