# Tarka 12-Month Category Charters

These one-page charters define mission, scope, and 12-month outcomes for each roadmap category.

## Security Charter

- Mission: make trust-by-default enforceable across service, tenant, and workload boundaries.
- Scope: authN/Z, tenant isolation, policy-as-code, service identity, key lifecycle, audit integrity.
- 12-month outcomes: policy enforcement in default profiles, no critical auth bypasses in release trains, zero-downtime key rotation drills.
- Core interfaces: `services/shared/*auth*`, `deploy/opa/*`, deployment profiles, release gates.

## Compliance Charter

- Mission: make compliance readiness measurable, repeatable, and auditable without slowing delivery.
- Scope: control mappings, evidence artifact generation, data handling profiles, launch sign-off.
- 12-month outcomes: release-scoped evidence packs, documented regional data policies, pre-audit simulation workflows.
- Core interfaces: compliance guides, release readiness checklists, control evidence telemetry.

## AI-Copilot Charter

- Mission: increase analyst throughput while preserving explainability and safety.
- Scope: confidence scoring, citation fidelity, HITL guardrails, persona boundaries, feedback loops.
- 12-month outcomes: measurable citation quality uplift, safe-action gating for high-impact actions, lower analyst rework.
- Core interfaces: investigation-agent, chat bridge, case workflow, copilot observability.

## Analytics Charter

- Mission: convert operational and risk events into product, trust, and executive decision intelligence.
- Scope: benchmark analytics, drift intelligence, investigation efficiency metrics, self-serve analytics packs.
- 12-month outcomes: cross-surface KPI dashboards, faster drift detection, tenant-safe benchmark exports.
- Core interfaces: analytics-sink, ClickHouse, frontend analytics views, SLO scorecards.

## UI/UX Charter

- Mission: deliver an investigation experience that is explainable, resilient, and action-oriented.
- Scope: analyst workbench flows, degraded-mode handling, accessibility, workflow automation, simulator UX.
- 12-month outcomes: lower task time-to-completion, improved error recoverability, higher workflow consistency.
- Core interfaces: frontend pages, API client contracts, design system patterns, product telemetry.

## Graph and Entity Charter

- Mission: turn entity linkage into explainable, high-confidence risk intelligence.
- Scope: graph reasoning, temporal context, ring patterns, confidence calibration, feature export.
- 12-month outcomes: explainable graph path usage in investigations, measurable entity resolution quality improvements.
- Core interfaces: graph-service, Neo4j models, investigation views, rules/ML feature pipelines.

## Platform and Deployment Charter

- Mission: provide repeatable, portable deployment paths for hosted and self-hosted customers.
- Scope: presets, overlays, managed-service abstraction, progressive delivery, diagnostics.
- 12-month outcomes: reliable preset promotion flow, lower deployment drift, faster support triage via environment diagnostics.
- Core interfaces: Helm chart, Compose profiles, Kustomize overlays, CI smoke/test pipelines.

## Reliability and SRE Charter

- Mission: keep critical fraud workflows available, observable, and recoverable under stress.
- Scope: SLO/error budgets, burn alerts, queue/backpressure controls, incident and DR operations.
- 12-month outcomes: consistent SLO attainment, validated DR rehearsal cadence, lower mean recovery time.
- Core interfaces: Prometheus/Grafana rules, runbooks, incident playbooks, reliability tests.

## Data Governance and MLOps Charter

- Mission: make feature/model/rule lifecycles governed, reproducible, and auditable.
- Scope: lineage, parity checks, experiment governance, promotion workflow controls, rollback safety.
- 12-month outcomes: automated parity reporting, lineage completeness for promoted artifacts, governed experiments in production paths.
- Core interfaces: model/feature metadata, experiment registry, CI validation jobs, policy gates.

## Integrations and Ecosystem Charter

- Mission: scale ecosystem value through reliable connectors and stable extension contracts.
- Scope: connector SDKs, contract versioning, third-party evidence ingestion, extension points.
- 12-month outcomes: higher connector reliability, partner-ready integration contracts, reduced integration MTTR.
- Core interfaces: integration-ingress, collaboration bridge, contracts/openapi, partner docs.
