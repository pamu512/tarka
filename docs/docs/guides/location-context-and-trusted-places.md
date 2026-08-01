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

## Co-presence demo (productize path)

Location Service scores co-presence from counter-style features (e.g. `distinct_session_id_24h` > 1). Decision API merges `location_meta.copresence_risk` into evaluate features / `inference_context` so JSON rules can hit on it.

```bash
# Lite stack (location mounted at /location) or LOCATION_API=http://host:port
python3 scripts/oss/copresence_demo.py
```

Example rule pack (shadow by default): `services/decision-api/rules/location_copresence_v1.json`.

Graph `SEEN_AT` / place peers also feed colocation heuristics inside `build_inference_context` when peer counts are present; the demo above proves the location-service → feature path without requiring a full graph seed.

## Analyst usage

- Case detail shows location confidence and risk metrics.
- Evidence bundles include location-derived tags and metrics for audit trails.
