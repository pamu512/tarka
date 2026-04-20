# Location Context and Trusted Places

Tarka merges geo signals from payload + SDK signals into a normalized location context used by Decision API and Location Service.

## Input fields

- `payload.session_last_lat`, `payload.session_last_lon`, `payload.session_last_ts`
- `payload.session_prev_lat`, `payload.session_prev_lon`, `payload.session_prev_ts`
- `device_context.signals.geo_lat`, `geo_lon`, `geo_ts`
- `payload.trusted_zones` (optional per-request trusted places)

## Derived inference outputs

- `geo_consistency_risk`
- `copresence_risk` / `colocation_risk`
- `impossible_travel_risk`
- `location_confidence`

These are surfaced under `inference_context` and evidence bundles.

## Trusted places

Trusted places are merged from:

1. Request payload (`trusted_zones`)
2. Tenant trusted-zone config loaded from Decision API rules path

When current location falls into a trusted zone, impossible-travel and geo inconsistency penalties are softened.

## Analyst usage

- Case detail shows location confidence and risk metrics.
- Evidence bundles include location-derived tags and metrics for audit trails.
