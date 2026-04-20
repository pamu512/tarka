# Scameter Connector

Decision API supports external risk enrichment through a connector abstraction (`ExternalSignalProvider`).
The first implementation is `ScameterSignalProvider`.

## Configuration

- `SCAMETER_ENABLED=true`
- `SCAMETER_BASE_URL=https://...`
- `SCAMETER_API_KEY=...`
- `EXTERNAL_SIGNAL_TIMEOUT_SECONDS=1.8` (default)

## Runtime behavior

On evaluate:

1. Decision API calls Scameter lookup (`/v1/risk/lookup`) with tenant/entity/event context.
2. Risk output is converted into:
   - additive score delta (bounded),
   - signal tags (`scameter_high_risk`, `scameter:*`),
   - enrichment payload under `external_signals`.
3. `inference_context` captures:
   - `external_signal_score`,
   - `external_signal_providers`.

Failures are non-blocking: evaluate continues with core signals when connector is unavailable.
