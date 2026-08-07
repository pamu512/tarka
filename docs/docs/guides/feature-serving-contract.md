# Feature Serving Contract

**Schema:** `tarka.feature_serving_contract/v1`  
**Discover:** `GET /v1/feature-serving-contract` on feature-service

## Guarantees

| Term | Meaning |
|---|---|
| Online store | Redis aggregate keys (`fraud:agg:*`) shared with decision-api evaluate |
| TTL | Default velocity TTL via `FEATURE_VELOCITY_TTL_SECONDS` (see contract endpoint) |
| Zero-fallback | On miss, counters may return 0 — callers must treat this as *unknown/zero*, not proven clean, when `FEATURE_ZERO_FALLBACK=true` |
| Online/offline parity | `POST /v1/internal/parity/verify` + `scripts/oss/counter_parity_dual_diff.py` |

## Not Feast / Not Flink

This is Tarka’s own contract. Feast and Flink are not dependencies.

**Ops posture:** `GET /v1/ops/feature-store-posture` (decision-api) — `ops_ready` when Redis online is configured **and** `counter_parity_last.json` proves dual-diff. `feast_class_claim_allowed` and `streaming_flink_claim_allowed` stay **false** even when ops-ready (L1 parity ≠ Feast/Flink product).

Ops UI: **Counters** (`/ops/counters`) and **Feature tools** (`/ops/features`).

## Auth path

Velocity reads stay on the auth path. Heavy OSINT/enrichment is optional and must emit degrade tags when skipped or failed — see [auth-vs-forensics-path.md](./auth-vs-forensics-path.md).
