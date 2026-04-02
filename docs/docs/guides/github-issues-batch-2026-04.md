# GitHub Issues Batch (April 2026)

Use this as a copy/paste issue pack. Each issue includes title, description, and acceptance criteria.

## 1) Epic A: Define and publish `inference_context` contract

**Description**
Add a normalized `inference_context` schema to OpenAPI and align SDK payload/response typings.

**Acceptance Criteria**
- OpenAPI includes `inference_context` fields used by decision responses.
- Python/TypeScript/Android/iOS SDK typings include the contract.
- Contract tests fail on schema drift.

## 2) Epic A: Derive normalized inference fields in decision pipeline

**Description**
Compute `integrity_confidence`, `tamper_risk`, `network_trust`, `replay_risk`, and `geo_consistency_risk` in `decision-api`.

**Acceptance Criteria**
- Fields are present in decision outputs for supported checkpoints.
- Fallback behavior is deterministic when source signals are missing.
- Unit tests cover score derivation branches.

## 3) Epic A: Add explainability drivers to audit records

**Description**
Persist top inferred risk drivers into audit output so analysts can explain decisions.

**Acceptance Criteria**
- Audit API includes ordered driver list with contribution labels.
- Case UI can render top drivers without parsing raw logs.
- Tests verify traceability from decision to audit explanation.

## 4) Epic B: SDK request envelope signing

**Description**
Add timestamp/nonce/payload-hash envelope fields in SDK clients for ingress integrity checks.

**Acceptance Criteria**
- All SDKs send envelope fields when configured.
- Envelope signature/hash generation is deterministic across platforms.
- Backward compatibility preserved for clients not yet upgraded.

## 5) Epic B: Replay detection at decision ingress

**Description**
Implement replay cache checks and mark repeated payload submissions.

**Acceptance Criteria**
- Duplicate payload within replay window is flagged.
- Replay flags are visible in decision output and audit trail.
- Integration tests simulate duplicate submissions and pass.

## 6) Epic B: Tamper mismatch reasons and policy actions

**Description**
Emit structured tamper reason codes and support policy-driven actions in rules.

**Acceptance Criteria**
- Reason codes are stable and documented.
- Rules can reference tamper flags/reasons.
- Tests cover at least 3 tamper mismatch scenarios.

## 7) Epic C: Multi-window counter service (5m/1h/24h)

**Description**
Add counter primitives for short/medium/day windows for velocity-style risk features.

**Acceptance Criteria**
- Counter queries return deterministic values for 5m/1h/24h.
- Counters are available to decision feature generation.
- Load tests confirm expected latency under benchmark volume.

## 8) Epic C: Normalized velocity feature keys for rules and ML

**Description**
Expose stable feature keys (device/account/ip velocity) for rules and model inputs.

**Acceptance Criteria**
- Feature key naming is documented and versioned.
- Rule engine and model pipeline both consume the same keys.
- Simulation snapshots include velocity features.

## 9) Epic C: Historical replay utility for counters

**Description**
Create utility to rebuild counters from historical payload snapshots.

**Acceptance Criteria**
- Replay command can regenerate counters for a specified date range.
- Replayed output can be compared to live output for drift checks.
- CI includes a replay consistency test fixture.

## 10) Epic D/E: Challenge orchestration + location coherence

**Description**
Add risk-tier challenge templates with escape hatches and introduce co-location/impossible-travel features.

**Acceptance Criteria**
- Challenge policy supports low-friction-first escalation.
- Co-location and impossible-travel features include confidence metadata.
- End-to-end tests verify challenge behavior at low/medium/high risk tiers.

## 11) Epic F: Analyst evidence summary endpoint

**Description**
Add investigation-agent endpoint that summarizes case/graph risk evidence with citations.

**Acceptance Criteria**
- Output includes citations to trace IDs/evidence artifacts.
- Summary is deterministic for fixed test inputs.
- UI can render summary and confidence labels.

## 12) Epic F: Outcome-to-label ingestion and KPI overlays

**Description**
Ingest dispute outcomes into model governance labels and expose baseline-vs-current KPI overlays.

**Acceptance Criteria**
- Label ingestion path accepts outcome events and updates governance records.
- Frontend dashboard shows baseline/current deltas with confidence intervals.
- Integration tests verify label flow and KPI refresh behavior.
