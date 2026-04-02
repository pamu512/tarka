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

## Day 30 (v1.1.0): Core Inference and Integrity Foundation

### Scope

- Ship Epic A core (`inference_context` contract + derived risk fields + audit explainability drivers).
- Ship Epic B core (request envelope signing, replay checks, tamper reason codes).
- Add baseline benchmark harness skeleton and fixed seed datasets.
- Add integration quality gate framework (contract tests + probe semantics).

### Deliverables

- `decision-api`: inference field derivation and replay/tamper ingress enforcement.
- `contracts/openapi`: `inference_context` schema and response contract updates.
- `sdk` packages: envelope signing payload fields for client submissions.
- `docs`: inference and integrity signal contract documentation.
- `ci`: benchmark runner scaffold and nightly baseline metric capture.
- `integration-ingress`: connector test contract spec and quality rubric.

### Acceptance Tests

- All SDKs and APIs validate against the same `inference_context` contract.
- Replay detection flags duplicate payloads within configured windows.
- Tamper mismatches emit structured reason codes and audit records.
- Audit responses include top inference drivers for analyst review.
- Baseline benchmark run is deterministic for fixed seed and data snapshot.
- Connector quality checks fail builds on missing contract assertions.

## Day 60 (v1.2.0): Velocity, Challenge, and Location Coherence

### Scope

- Ship Epic C (5m/1h/24h counters, normalized feature keys, replay utility).
- Ship Epic D (risk-tier challenge orchestration with low-friction-first templates).
- Ship Epic E core (co-location risk feature, impossible-travel checks, location confidence fields).
- Add benchmark harness for precision/recall/lift comparisons.
- Add connector reliability scorecards and runbook-backed failure handling.

### Deliverables

- `feature-service`: multi-window counter and velocity aggregation interfaces.
- `decision-api`: challenge orchestration policy templates and escalation behavior.
- `rules`: normalized velocity and location coherence keys available to rule authors.
- `simulation`: benchmark runner with baseline vs profile comparisons.
- `frontend`: challenge policy and reliability panels.
- `integration-ingress`: provider reliability dashboard and SLA status fields.

### Acceptance Tests

- Counter features are queryable and deterministic for 5m/1h/24h windows.
- Challenge orchestration escalates correctly by risk tier and supports escape hatches.
- Co-location and impossible-travel features are emitted with confidence fields.
- Benchmark harness outputs reproducible metrics with fixed seed.
- Integration reliability panel flags degraded connectors with actionable remediation.

## Day 90 (v1.3.0): Analyst Copilot and Enterprise Operationalization

### Scope

- Ship Epic F (evidence-grounded case summaries, KPI overlays, auto-label ingestion).
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

## Global Quality Gates

- Contract tests pass for all new request/response fields.
- Rule simulation snapshots cover newly introduced inference features.
- Replay/tamper paths pass integration tests.
- Lint, type checks, and smoke tests are green before each release.
