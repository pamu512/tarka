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

## Day 30 (v1.1.0): Consortium v2 Foundation

### Scope

- Add consortium confidence scoring with tenant trust weighting.
- Add false-positive suppression feedback loop for consortium hits.
- Add per-tenant controls for consortium participation and data-sharing policy.
- Add operational dashboard metrics for consortium hit quality.
- Add baseline benchmark harness skeleton and fixed seed datasets.
- Add integration quality gate framework (contract tests + probe semantics).

### Deliverables

- `decision-api`: weighted consortium scoring endpoint and runtime integration.
- `case-api`: analyst feedback endpoint to mark consortium hit quality.
- `frontend`: consortium controls and performance panel.
- `docs`: consortium governance and privacy model documentation.
- `ci`: benchmark runner scaffold and nightly baseline metric capture.
- `integration-ingress`: connector test contract spec and quality rubric.

### Acceptance Tests

- Weighted score changes with tenant trust and report quality.
- False-positive feedback reduces repeat score impact for matched entities.
- Disabling consortium for a tenant produces no consortium score delta.
- API + UI tests for consortium settings and quality metrics pass.
- Baseline benchmark run is deterministic for fixed seed and data snapshot.
- Connector quality checks fail builds on missing contract assertions.

## Day 60 (v1.2.0): Vertical Intelligence Packs

### Scope

- Ship vertical starter packs (fintech, e-commerce, gaming).
- Include tuned rule packs, model presets, workflows, and reason code maps.
- Add benchmark harness for precision/recall/lift comparisons.
- Add business KPI readout per pack (review-rate, deny-rate, false-positive rate, analyst load).
- Add connector reliability scorecards and runbook-backed failure handling.

### Deliverables

- `rules`: three curated production-ready pack sets.
- `ml-scoring`: vertical model profile selection and metadata.
- `simulation`: benchmark runner with baseline vs pack comparisons.
- `docs`: deployment and tuning guides per vertical.
- `frontend`: value-pack KPI page with baseline vs projected lift narrative.
- `integration-ingress`: provider reliability dashboard and SLA status fields.

### Acceptance Tests

- Each vertical pack can be installed and activated via API/UI.
- Benchmark harness outputs reproducible metrics with fixed seed.
- Vertical packs outperform generic baseline on provided sample datasets.
- Smoke tests pass for all vertical profiles.
- KPI dashboard reflects benchmark outputs and confidence intervals.
- Integration reliability panel flags degraded connectors with actionable remediation.

## Day 90 (v1.3.0): Enterprise Trust Center

### Scope

- Expose audit evidence endpoints for key controls and policy changes.
- Add support/SLA views and incident readiness status page in frontend.
- Add release governance checklist and signed release artifact process.
- Add analyst copilot workflows for case/graph evidence summary and recommended actions.
- Publish enterprise proof kit mapped to procurement and audit expectations.

### Deliverables

- `decision-api` + `case-api`: evidence export APIs.
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
