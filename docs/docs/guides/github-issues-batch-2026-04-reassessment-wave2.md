# GitHub Issues Batch (April 2026, Reassessment Wave 2)

Use this as a copy/paste issue pack for the new reassessment set.  
Format mirrors prior batches: each issue includes swimlane mapping, labels, scope, and acceptance criteria.

## Recommended labels for all issues in this pack

- `borrowed-from-OSS`
- `planning`
- `roadmap`
- `enhancement`

Optional labels by topic:

- `drift-resilience`
- `graph-ml`
- `case-management`
- `feature-engineering`
- `integration`

## 1) Epic G: Productized AML/fraud operations slice (Jube-inspired)

**Module swimlane**  
`Case API` + `Frontend` + `Decision API` + `Analytics Sink`

**Source pattern**  
Jube workflow-driven case operations and hybrid rule/ML operations.

**Description**  
Deliver a cohesive analyst-operations slice that combines decision outcomes, rule events, and case workflows with auditable escalations.

**Acceptance Criteria**

- Case workflow states and escalation triggers are documented and API-backed.
- Rule and ML decision evidence are viewable in a single case timeline.
- Audit trail records all status transitions and assignment changes.

## 2) Add case escalation policy engine with deterministic transitions

**Module swimlane**  
`Case API`

**Depends on**  
Epic G

**Description**  
Add deterministic case transition policies (new, triage, review, escalated, closed) with rule-triggered and risk-triggered transitions.

**Acceptance Criteria**

- Transition matrix is explicitly defined and validated server-side.
- Invalid transitions are rejected with structured error codes.
- Policy tests cover auto-escalation, manual override, and closure.

## 3) Add analyst queue views for SLA, risk, and aging prioritization

**Module swimlane**  
`Frontend`

**Depends on**  
#2

**Description**  
Add queue presets and saved views for SLA-first, highest-risk-first, and oldest-open-first triage.

**Acceptance Criteria**

- Queue presets are available in UI with stable filter semantics.
- Counts and pagination remain consistent across refreshes.
- Views support exportable filters for audit/reporting.

## 4) Epic H: Drift-resilient model lifecycle (PKBoost-inspired)

**Module swimlane**  
`ML Scoring` + `Analytics Sink`

**Source pattern**  
Concept drift resilience and adaptation-first benchmarking.

**Description**  
Add drift detection and adaptation controls to preserve fraud performance under changing distributions.

**Acceptance Criteria**

- Drift score is computed and persisted per model/version window.
- Retrain recommendations are generated from configurable thresholds.
- Performance deltas under drift are visible in model governance views.

## 5) Add drift benchmark harness with seeded shift scenarios

**Module swimlane**  
`ML Scoring`

**Depends on**  
Epic H

**Description**  
Build reproducible benchmark scenarios (covariate shift, label shift, mixed shift) to measure degradation and recovery.

**Acceptance Criteria**

- Benchmark runner supports seeded scenarios and deterministic outputs.
- Metrics include PR-AUC, recall-at-precision, and calibration drift.
- CI can run a lightweight drift benchmark profile.

## 6) Add adaptive retrain trigger policy and cooldown controls

**Module swimlane**  
`ML Scoring`

**Depends on**  
#5

**Description**  
Introduce policy-driven retrain triggers with cooldown windows to prevent retrain thrash during noisy periods.

**Acceptance Criteria**

- Trigger policy supports threshold, persistence window, and cooldown.
- Trigger events are auditable with reason and metric snapshot.
- Manual override can defer or force retraining safely.

## 7) Epic I: Online graph inference serving parity (waittim + NebulaGraph-inspired)

**Module swimlane**  
`Graph Service` + `ML Scoring` + `Integration Ingress`

**Source pattern**  
Subgraph extraction -> model inference -> online decision path.

**Description**  
Standardize online graph inference APIs and serving contracts for low-latency fraud decisions.

**Acceptance Criteria**

- Subgraph extraction contract is versioned and validated.
- Inference path supports timeout and degraded fallback behavior.
- End-to-end traces link ingress request to graph inference output.

## 8) Add graph subgraph snapshot API for online inference requests

**Module swimlane**  
`Graph Service`

**Depends on**  
Epic I

**Description**  
Expose API to return bounded k-hop subgraph snapshots with deterministic node/edge shaping for inference.

**Acceptance Criteria**

- API supports tenant, entity, horizon, and hop limits.
- Response schema includes truncation metadata when limits apply.
- Latency SLO is documented and tested under load profile.

## 9) Add graph inference adapter in decision path with fail-safe fallback

**Module swimlane**  
`Decision API`

**Depends on**  
#8

**Description**  
Call graph inference during decision evaluation with clear fallback behavior when graph services are unavailable.

**Acceptance Criteria**

- Decision path records when graph inference is used vs bypassed.
- Fallback adds explicit reason tags and does not break responses.
- Audit snapshot contains graph inference summary when available.

## 10) Epic J: Behavior-first feature layer (feature-engineering paper-inspired)

**Module swimlane**  
`Feature Service` + `Decision API` + `Analytics Sink`

**Source pattern**  
Rolling behavioral aggregations for fraud scoring uplift.

**Description**  
Add a stable behavioral feature layer using rolling windows and entity-centric aggregations.

**Acceptance Criteria**

- Canonical feature keys and window definitions are published.
- Features are accessible to rules and ML through one contract.
- Backfill/replay path validates parity with online feature values.

## 11) Add rolling aggregate feature set (24h, 72h, 168h) by entity and channel

**Module swimlane**  
`Feature Service`

**Depends on**  
Epic J

**Description**  
Implement rolling aggregates for counts, amounts, distinct counterparties, and velocity by key entities.

**Acceptance Criteria**

- Aggregates are available by account, device, IP, and merchant where applicable.
- Feature freshness metadata is included with values.
- Unit and integration tests validate window boundary correctness.

## 12) Add feature value lineage and explainability links in audit output

**Module swimlane**  
`Decision API`

**Depends on**  
#11

**Description**  
Attach feature provenance pointers and top-contributing feature values to decision audit payloads.

**Acceptance Criteria**

- Audit output includes feature key, value, window, and source timestamp.
- Explainability payload is deterministic for fixed inputs.
- Frontend can render top feature contributors without raw log parsing.

## 13) Epic K: Investigation-side statistical detectors (Benford plugin)

**Module swimlane**  
`Analytics Sink` + `Investigation Agent`

**Source pattern**  
Digit-distribution anomaly detection for accounting/payment anomaly surfaces.

**Description**  
Add optional Benford-style statistical checks for investigation workflows and anomaly surfacing.

**Acceptance Criteria**

- Detector can run on selected numeric fields and return confidence stats.
- Outputs are tagged as investigative signals, not direct deny decisions.
- Results are explorable in analyst UI/export.

## 14) Add Benford detector plugin with configurable field profiles

**Module swimlane**  
`Analytics Sink`

**Depends on**  
Epic K

**Description**  
Implement configurable Benford checks for first/second/last-digit distributions by dataset profile.

**Acceptance Criteria**

- Profiles define eligible fields, minimum sample size, and thresholds.
- Output includes observed vs expected distributions and divergence score.
- Plugin can run in scheduled and on-demand modes.

## 15) Add investigation assistant summary block for statistical anomalies

**Module swimlane**  
`Investigation Agent`

**Depends on**  
#14

**Description**  
Generate concise summaries that explain statistical anomaly findings with citations to underlying evidence artifacts.

**Acceptance Criteria**

- Summary includes detector name, fields assessed, and confidence statement.
- Evidence citations link to dataset snapshots or report artifacts.
- Summaries are deterministic for fixed evidence sets.

## 16) Epic L: External KYC/ID verification connector hardening (LibraX-style adapter)

**Module swimlane**  
`Integration Ingress`

**Source pattern**  
Simple API-first ID verification adapter with provider abstraction.

**Description**  
Add provider-neutral ID verification connector contract with consistent response normalization.

**Acceptance Criteria**

- Connector contract supports request/response normalization across providers.
- Timeouts, retries, and circuit-breaker behavior are documented and tested.
- PII handling and audit boundaries are explicitly defined.

## 17) Add ID verification adapter contract + mock provider for integration tests

**Module swimlane**  
`Integration Ingress`

**Depends on**  
Epic L

**Description**  
Create adapter interface and mock provider so KYC pipelines can be tested without vendor lock-in.

**Acceptance Criteria**

- Adapter contract supports confidence score, match status, and reason codes.
- Mock provider fixtures cover pass, fail, timeout, and malformed response.
- Contract tests enforce stable normalized schema.

## Dependency edges (must-do-before)

Use these edges as issue comments (`blocked-by` / `blocks`) when creating issues:

- Epic G -> #2 -> #3
- Epic H -> #5 -> #6
- Epic I -> #8 -> #9
- Epic J -> #11 -> #12
- Epic K -> #14 -> #15
- Epic L -> #17
- #11 -> #9 (decision path should consume stable behavior features)
- #5 -> #9 (graph inference rollout should include drift benchmark guardrails)
- #2 -> #15 (investigation summaries should align with case workflow states)

## Topological ship order (recommended)

1. **Tier 0 (Foundations):** Epic G, Epic H, Epic I, Epic J, Epic K, Epic L  
2. **Tier 1 (Core contracts):** #2, #5, #8, #11, #14, #17  
3. **Tier 2 (Decision/investigation integration):** #9, #12, #15  
4. **Tier 3 (Operational UX and governance):** #3, #6

## Suggested swimlane assignment map

- `Case API`: Epic G, #2
- `Frontend`: #3
- `ML Scoring`: Epic H, #5, #6
- `Graph Service`: Epic I, #8
- `Decision API`: #9, #12
- `Feature Service`: Epic J, #11
- `Analytics Sink`: Epic K, #14
- `Investigation Agent`: #15
- `Integration Ingress`: Epic L, #17

## Suggested milestone packaging

- **Week 1:** Tier 0 epics + contract issue kickoff  
- **Week 2:** Tier 1 issues complete (`#2/#5/#8/#11/#14/#17`)  
- **Week 3:** Tier 2 integrations (`#9/#12/#15`)  
- **Week 4:** Tier 3 operationalization (`#3/#6`) and stabilization
