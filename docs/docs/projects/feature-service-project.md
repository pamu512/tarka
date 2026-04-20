# Feature Service Project

## Scope

Feature snapshot generation, counter windows, and online/offline feature parity.

**Parity gate (OSS #48):** `POST /v1/internal/parity/verify` compares live Redis velocity counters to caller-supplied `expected` within `epsilon` (same `AggregateStore` path as `POST /v1/velocity/query`). Tests: `services/feature-service/tests/test_parity_verify.py`. Contract: `contracts/openapi/feature-service.yaml`. Index: [API Reference — Feature Service](../api-reference.md#feature-service).

## Current Gaps

- Multi-window counter platform is not fully productized yet.
- Replayability and deterministic parity workflows need hardening.

## Roadmap

### Now

- Ship stable 5m/1h/24h counter contracts for downstream rules and ML.
- Improve deterministic replay and snapshot consistency checks.

### Next

- Add richer feature lineage and traceability by checkpoint/event type.
- Add counter quality telemetry and SLA surfaces.

### Later

- Self-serve feature DSL with safe rollout and validation guardrails.
