# 30/60/90 Delivery Plan

This roadmap converts the latest competitive gap analysis into concrete milestones with acceptance tests.

## Milestone Dates

- Day 30 release target: `2026-04-30` (`v1.1.0`)
- Day 60 release target: `2026-05-30` (`v1.2.0`)
- Day 90 release target: `2026-06-29` (`v1.3.0`)

## Competitive Priorities Added

This plan now explicitly addresses the highest competitive gaps identified against leading vendors:

- Faster time-to-value with opinionated vertical value packs.
- Reproducible benchmark scorecards (precision/recall/lift, false-positive cost).
- Integration quality gates and connector reliability SLAs.
- Analyst copilot workflows for evidence summarization and next-best actions.
- Enterprise proof kit for procurement (controls evidence, DR tests, uptime/error-budget reporting).

## Epic Alignment

- **Epic A (P0)**: Inference schema normalization.
- **Epic B (P0)**: Replay/tamper hardening.
- **Epic C (P0)**: Counter and velocity features.
- **Epic D (P1)**: Challenge orchestration and UX safety.
- **Epic E (P1)**: Cross-surface location coherence.
- **Epic F (P1)**: Analyst productivity and benchmarking.

## Day 30 (v1.1.0): Core Inference, Integrity, and First Slice of C/D/E/F (2026-04-30)

### Scope

- Ship Epic A: **`inference_context` v2** (tier, `driver_reasons`, versioned schema).
- Ship Epic B core: replay/tamper signals reflected in inference and audit explainability.
- Ship Epic C **in decision aggregates**: **5m / 1h / 24h** event counts surfaced in inference (`velocity_events_*`).
- Ship Epic D **hint layer**: **`recommended_action`** on evaluate + audit (step-up / review / block hints).
- Ship Epic E **proxies in inference**: colocation and impossible-travel risk fields.
- Ship Epic F **first slice**: analyst-facing drivers in API + **Case Detail** explainability UI.
- Consortium v2: weighted scoring, FP suppression, tenant policies, quality metrics (see release notes).
- Baseline benchmark harness skeleton and integration quality gates (as capacity allows).

### Deliverables

- `decision-api`: `inference_build` module, aggregates `event_count_5m`, audit/evaluate **`recommended_action`**, simulation **`experiment_guardrails`**.
- `contracts/openapi`: v2 **`InferenceContext`**, **`recommended_action`** on **`EvaluateResponse`**.
- `packages/fraud-sdk-python` + `packages/fraud-sdk-typescript`: typed evaluate response parity.
- `frontend`: Case Detail panel (tier, velocity, travel/colocation, drivers, recommended action); **`mockData`** v2.
- `docs`: `docs/docs/releases/v1.1.0-2026-04-30.md` as the 4/30 ship manifest; companion **examples** ([`docs/docs/guides/examples/`](./examples/README.md)), **extension guides** (OSINT, ONNX, shadow/A-B, borrowed OSS), and **benchmark script** ([`scripts/benchmarks/`](../../../scripts/benchmarks/README.md)) to reduce “architecture without proof” friction.
- `ci`: unit tests for inference build; contract/smoke gates as defined in release notes.

### Acceptance Tests

- Evaluate and audit return **`inference_context`** v2 with tier, drivers, and velocity fields where aggregates exist.
- **`recommended_action`** present and consistent with documented hint semantics for sampled scenarios.
- OpenAPI + Python + TypeScript types agree on new fields.
- UI renders audit/evaluate inference fields without errors when backend sends v2 payloads.
- Consortium, replay, and tamper acceptance items from **`v1.1.0`** release notes pass before tag.

## Day 60 (v1.2.0): Deeper Velocity, Policy-Grade Challenge, and Reliability

**Strategic concentration** for 5/30 is enumerated in [`releases/v1.2.0-2026-05-30.md`](../releases/v1.2.0-2026-05-30.md) § *Strategic concentration (5/30 train)* (productized quality, device/session/integrity, location & co-presence, counters/velocity platform, analyst workflows, network/consortium, operations & lock-in inverse).

### Scope

- Epic C **deeper**: `feature-service` multi-window counters and normalized velocity keys for rule authors (beyond decision-api aggregates).
- Epic D **policy templates**: challenge orchestration configs and escalation behavior (beyond evaluate hints).
- Epic E **richer**: location confidence fields and rule-facing keys where not covered by inference proxies alone.
- Benchmark harness for precision/recall/lift comparisons.
- Connector reliability scorecards and runbook-backed failure handling.

### Deliverables

- `feature-service`: multi-window counter and velocity aggregation interfaces.
- `decision-api`: challenge orchestration policy templates and escalation behavior (extends **`recommended_action`** hints).
- `rules`: normalized velocity and location coherence keys for rule packs.
- `simulation`: benchmark runner with baseline vs profile comparisons (extends guardrails shipped in v1.1.0).
- `frontend`: challenge policy and reliability panels.
- `integration-ingress`: provider reliability dashboard and SLA status fields.

### Acceptance Tests

- Counter features are queryable and deterministic for 5m/1h/24h windows from feature pipelines.
- Challenge orchestration escalates correctly by risk tier and supports escape hatches.
- Co-location and impossible-travel signals are available to rules with documented confidence semantics.
- Benchmark harness outputs reproducible metrics with fixed seed.
- Integration reliability panel flags degraded connectors with actionable remediation.

## Day 90 (v1.3.0): Analyst Copilot and Enterprise Operationalization

### Scope

- Ship Epic F **remainder** (evidence-grounded case summaries, KPI overlays, auto-label ingestion)—building on drivers and UI shipped in v1.1.0.
- Expose audit evidence endpoints for key controls and policy changes.
- Add support/SLA views and incident readiness status page in frontend.
- Add release governance checklist and signed release artifact process.
- Publish enterprise proof kit mapped to procurement and audit expectations.

### Deliverables

- `decision-api` + `case-api`: evidence export APIs and model-label feedback ingestion endpoints.
- `frontend`: Trust Center page (controls, readiness, runbook links).
- `docs`: operational attestations, support model, and control mappings.
- `ops`: release readiness checklist integrated in CI.
- `investigation-agent`: guided case narrative and next-step recommendation endpoint.
- `docs`: procurement package (control matrix, DR test report, uptime/error-budget evidence).

### Acceptance Tests

- Evidence export includes auditable control history for sampled changes.
- Trust Center reflects service health and readiness documents.
- CI blocks release if governance checklist is incomplete.
- Release notes and artifacts are generated from tagged builds.
- Copilot summaries are traceable to underlying evidence and include confidence labels.
- Procurement package is fully reproducible from tagged build artifacts.

## Gap closure vs competition

See **[release-gap-closure-schedule.md](./release-gap-closure-schedule.md)** for what **`v1.1.0`** and **`v1.2.0`** close against the April 2026 competitive review, and what remains for **`v1.3.0`**.

## Global Quality Gates

- Contract tests pass for all new request/response fields.
- Rule simulation snapshots cover newly introduced inference features.
- Replay/tamper paths pass integration tests.
- Lint, type checks, and smoke tests are green before each release.
