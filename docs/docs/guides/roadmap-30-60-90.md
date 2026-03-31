# 30/60/90 Delivery Plan

This roadmap converts the latest competitive gap analysis into concrete milestones with acceptance tests.

## Milestone Dates

- Day 30 release target: `2026-04-30` (`v1.1.0`)
- Day 60 release target: `2026-05-30` (`v1.2.0`)
- Day 90 release target: `2026-06-29` (`v1.3.0`)

## Day 30 (v1.1.0): Consortium v2 Foundation

### Scope

- Add consortium confidence scoring with tenant trust weighting.
- Add false-positive suppression feedback loop for consortium hits.
- Add per-tenant controls for consortium participation and data-sharing policy.
- Add operational dashboard metrics for consortium hit quality.

### Deliverables

- `decision-api`: weighted consortium scoring endpoint and runtime integration.
- `case-api`: analyst feedback endpoint to mark consortium hit quality.
- `frontend`: consortium controls and performance panel.
- `docs`: consortium governance and privacy model documentation.

### Acceptance Tests

- Weighted score changes with tenant trust and report quality.
- False-positive feedback reduces repeat score impact for matched entities.
- Disabling consortium for a tenant produces no consortium score delta.
- API + UI tests for consortium settings and quality metrics pass.

## Day 60 (v1.2.0): Vertical Intelligence Packs

### Scope

- Ship vertical starter packs (fintech, e-commerce, gaming).
- Include tuned rule packs, model presets, workflows, and reason code maps.
- Add benchmark harness for precision/recall/lift comparisons.

### Deliverables

- `rules`: three curated production-ready pack sets.
- `ml-scoring`: vertical model profile selection and metadata.
- `simulation`: benchmark runner with baseline vs pack comparisons.
- `docs`: deployment and tuning guides per vertical.

### Acceptance Tests

- Each vertical pack can be installed and activated via API/UI.
- Benchmark harness outputs reproducible metrics with fixed seed.
- Vertical packs outperform generic baseline on provided sample datasets.
- Smoke tests pass for all vertical profiles.

## Day 90 (v1.3.0): Enterprise Trust Center

### Scope

- Expose audit evidence endpoints for key controls and policy changes.
- Add support/SLA views and incident readiness status page in frontend.
- Add release governance checklist and signed release artifact process.

### Deliverables

- `decision-api` + `case-api`: evidence export APIs.
- `frontend`: Trust Center page (controls, readiness, runbook links).
- `docs`: operational attestations, support model, and control mappings.
- `ops`: release readiness checklist integrated in CI.

### Acceptance Tests

- Evidence export includes auditable control history for sampled changes.
- Trust Center reflects service health and readiness documents.
- CI blocks release if governance checklist is incomplete.
- Release notes and artifacts are generated from tagged builds.
