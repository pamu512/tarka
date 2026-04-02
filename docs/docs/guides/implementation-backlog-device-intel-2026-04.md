# Device Intelligence and Inference Backlog (Execution)

This backlog converts competitive findings into concrete engineering work.

## Epic A: Inference schema normalization (P0)

- **A1** Add `inference_context` contract in OpenAPI and SDK payload types.
- **A2** Add derived inference fields in decision pipeline:
  - `integrity_confidence`
  - `tamper_risk`
  - `network_trust`
  - `replay_risk`
  - `geo_consistency_risk`
- **A3** Persist top inference drivers into audit output for analyst explainability.

## Epic B: Replay/tamper hardening (P0)

- **B1** Add request envelope signing inputs (timestamp, nonce, payload hash) in SDK clients.
- **B2** Add replay cache check and replay flagging in decision ingress.
- **B3** Add tamper mismatch checks and structured reason codes.

## Epic C: Counter and velocity features (P0)

- **C1** Add multi-window counters for 5m/1h/24h.
- **C2** Add normalized feature keys consumable by rules and ML.
- **C3** Add replay utility to rebuild counters on historical payload snapshots.

## Epic D: Challenge orchestration and UX safety (P1)

- **D1** Add policy templates for low-friction-first challenge flows.
- **D2** Add challenge escalation by risk tier.
- **D3** Add fallback escape hatch behavior to reduce good-user lockout risk.

## Epic E: Cross-surface location coherence (P1)

- **E1** Add co-location risk feature for mobile approval vs web session.
- **E2** Add impossible-travel features with configurable thresholds.
- **E3** Add confidence fields for inferred location quality.

## Epic F: Analyst productivity and benchmarking (P1)

- **F1** Add evidence-grounded case summary endpoint in investigation agent.
- **F2** Add baseline vs current KPI overlays in frontend.
- **F3** Add auto-label ingestion path from dispute outcomes to model governance.

## Quality gates for all epics

- Contract tests for all new request/response fields.
- Rule simulation snapshots for new risk features.
- Integration tests for replay/tamper paths.
- Lint, type checks, and smoke tests green before release.

## Release phasing

- **Week 1**: Epic A + B foundations.
- **Week 2**: Epic C complete and integrated.
- **Week 3**: Epic D + E partial delivery.
- **Week 4**: Epic F + stabilization.
