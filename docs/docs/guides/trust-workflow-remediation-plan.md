# Trust-First Workflow Remediation Plan

## Goal

Restore analyst trust and workflow coherence across `Cases`, `Case Detail`, `Investigation`, and `Rules` by fixing reliability blockers first, then tightening grounding/evidence guarantees, then simplifying the end-to-end analyst journey.

## Guiding Principles

1. **Trust before throughput**: if a control appears available, it must be reliable and truthful.
2. **Fail transparently**: all degraded states must be explicit, actionable, and scoped.
3. **Case-centric coherence**: queue -> case -> investigate -> decide should feel like one workflow.
4. **Evidence over appearance**: grounding, claim provenance, and freshness indicators are first-class.

## Priority Structure

- **P0 (stability blockers)**: unblock core case and rules workflows.
- **P1 (trust hardening)**: prevent misleading partial functionality.
- **P2 (coherence & adoption)**: reduce cognitive load and align language.

---

## Phase 0 - Immediate Containment (0-48 hours)

### Objectives

- Stop user harm from misleading states.
- Prevent analysts from making decisions off broken context.

### Actions

1. **Feature gate broken surfaces**
   - Disable `Rules` navigation target when rules page crash condition is detected.
   - Disable case-dependent Investigation quick actions when case context APIs fail.
2. **Add temporary degraded banners**
   - Global status card in `Cases` and `Case Detail` showing service outage context.
3. **Error message uplift (hotfix)**
   - Replace raw `500 Internal Server Error` with structured fallback copy:
     - What failed
     - What still works
     - What to do next
4. **Ops escalation**
   - Create incident channel and owner rotation for ongoing failures.

### Exit Criteria

- No silent partial workflows.
- Analysts can distinguish healthy vs degraded paths instantly.

---

## Phase 1 - Reliability Restoration (Week 1)

### Objectives

- Make core analyst flows executable end-to-end.

### Workstream A: Case Workflow Reliability

1. Fix list endpoint chain:
   - `/v1/cases`
   - `/v1/case-views`
   - `/v1/cases/playbooks`
2. Fix case detail retrieval path (`/v1/cases/{id}`).
3. Fix create-case path (`POST /v1/cases`) including idempotency guard.
4. Add API contract tests for:
   - list
   - detail
   - create
   - views
   - playbooks

### Workstream B: Rules Availability

1. Null-safe normalize packs in frontend.
2. Filter out non-rule metadata packs from rule-card rendering.
3. Add defensive error boundary for `Rules` route.
4. Add fixture coverage for mixed pack schemas.

### Exit Criteria

- `Cases` list load success >= 99%.
- `Case detail` load success >= 99%.
- `Create case` success >= 98% (excluding validation errors).
- `Rules` crash-free sessions >= 99.9%.

---

## Phase 2 - Trust Hardening (Week 2)

### Objectives

- Ensure analysts can trust what is grounded, verified, and fresh.

### Workstream C: Grounding Integrity

1. Introduce explicit Investigation grounding status:
   - `Grounded`
   - `Partially grounded`
   - `Ungrounded`
2. Block or annotate actions requiring unavailable context.
3. Add one-click retry for failed context fetches.

### Workstream D: Evidence & Claim Contract

1. Enforce structured claim trailer generation in copilot responses.
2. Fail closed for high-risk responses missing provenance metadata.
3. Add telemetry:
   - claim-contract compliance rate
   - grounded-response rate
   - unsupported-claim rate

### Workstream E: Trust Signaling

1. Make sidebar counts health-aware (degraded marker + freshness timestamp).
2. Add stale data markers to queue metrics and badges.

### Exit Criteria

- Grounded-response rate visible in dashboard and stable.
- Unknown/unverified claim warnings reduced by target threshold.
- No confidence-signaling badges during backend outage.

---

## Phase 3 - Workflow Coherence and Adoption (Weeks 3-4)

### Objectives

- Reduce onboarding friction and unify analyst journey language.

### Workstream F: UX Coherence

1. Replace endpoint-centric UI strings with analyst-intent copy.
2. Progressive disclosure for preset catalog:
   - top starter presets
   - advanced grouped sections
3. Case-centric flow polish:
   - clearer transitions between queue, detail, and copilot
   - persistent case context identity chips and health state

### Workstream G: Unified Error Experience

1. Standard error contract schema across services:
   - `code`
   - `message`
   - `retryable`
   - `support_id`
2. Shared frontend error renderer with remediation guidance.

### Exit Criteria

- First-task completion time reduced for new analysts.
- Reduced support escalations tied to generic 500 errors.
- Positive qualitative feedback on workflow clarity.

---

## Ownership Model

- **Engineering Manager (Risk Ops Platform)**: overall delivery and risk tradeoffs.
- **Frontend Lead**: workflow coherence, degraded-state UX, error renderer.
- **Case API Lead**: list/detail/create reliability and contract stability.
- **Decision/Rules Lead**: rules payload normalization and route stability.
- **Investigation Lead**: grounding integrity and claim provenance enforcement.
- **SRE/Platform**: alerting, observability, incident readiness.
- **Risk Ops Design/PM**: copy and task-flow validation with analysts.

## Verification and Reporting Cadence

- Daily standup: blocker and incident review.
- Twice-weekly reliability scorecard:
  - list/detail/create success
  - rules crash-free rate
  - investigation grounded-response rate
- Weekly stakeholder review:
  - trust risk burn-down
  - workflow coherence demos

## Backlog Reference

Importable Jira backlog CSV:

- `docs/docs/guides/jira-backlog-trust-workflow.csv`

Recommended order: execute all `Highest` priority issues first, then `High`, then `Medium`.
