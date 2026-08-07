# Location Enrichment Reweight Design (C2/C7)

**Date:** 2026-08-06  
**Status:** Approved for planning  
**Closes:** Missed-mark C2 (location-at-signup linker assumption), C7 (equal-weight Location for loyalty thesis)  
**Related:** loyalty economics multi-gate (S9), critical regrade canvas, partner fusion hybrid

## Goal

Full product pass so **relatedness = graph + loyalty economics**, and **location = optional enrichment** — dual-write this release (new keys primary; old keys deprecated but still emitted).

## Non-goals

- Removing location-service, Incognia Place/SEEN_AT, or impossible-travel / spoofed-location signals.
- Hard-deleting `colocation_risk` or `location_cohort_evidence` this release.
- Requiring location for evaluate success.
- Claiming Location six-cap ≥4.0 without live partner pin (S1 still open).

## Product posture (locked)

| Concern | Primary | Enrichment |
| --- | --- | --- |
| Who is related | Graph (device / payment / referral / peers) | Partner Place/SEEN_AT, geo copresence |
| Is the cluster abusive (loyalty) | Loyalty economics gates (feeds + config) | — |
| Geo fraud | Impossible travel, spoofed location, geo mismatch | Trusted places soften |

## Dual-write contract (this release)

### Audit snapshot

| Key | Role |
| --- | --- |
| `relatedness_evidence` | **Primary** — `schema_id: tarka.relatedness_evidence/v1` with blocks `graph`, `device`, `geo_enrichment`, `tags` |
| `location_cohort_evidence` | **Deprecated alias** — same payload shape as today (or subset), still written when relatedness emits |

### `inference_context` (additive)

| Field | Role |
| --- | --- |
| `shared_device_risk` | Device/shared-device contribution (0–1) |
| `graph_peer_risk` | Graph peer / SEEN_AT peer contribution (0–1) |
| `geo_copresence_risk` | True geo/location-service copresence (0–1); 0 if no location meta |
| `colocation_risk` | **Deprecated composite** — `max(shared_device_risk, graph_peer_risk, geo_copresence_risk)` for backward compat |

Driver reasons: prefer `shared_device` / `graph_peers` over routing everything through a location-named driver when source is non-geo.

## Components

1. **`relatedness_evidence.py`** — build from existing inputs (tags, graph_meta, location_meta, partner hints); call from pipeline; also populate deprecated `location_cohort_evidence` via thin wrapper or shared builder.
2. **`inference_build.py`** — split risks; keep `colocation_risk` as max composite.
3. **OpenAPI** — document new fields; mark old keys deprecated.
4. **CaseDetail** — triage: Velocity | Graph | Loyalty (gates) primary; Geo demoted to enrichment row/secondary; copy: related ≠ abuse.
5. **Docs** — matrix + partner-fusion + gap-code-map reweight; canvas C2/C7 → mitigated in product posture (feeds still gate loyalty effectiveness).
6. **Rules** — optional shadow `graph_shared_device_v1.json`; keep `location_copresence_v1` for geo; document copresence_risk may be non-geo until consumers migrate.

## Frontend triage (CaseDetail)

Current flash cards: Velocity / Graph / Geo (equal).

Target:

1. Velocity  
2. Graph (linkage)  
3. Loyalty (advisory gates from `loyalty_economics_gates` when present; else “feeds required” / neutral)  
4. Geo (enrichment) — smaller/secondary, or fourth card labeled “Geo (enrichment)”

Hover copy for Loyalty: “Benefit gates (dispatch/redeem/order); not an order block. Related ≠ abusive.”

## Docs / scoring

- Location six-cap remains **enrichment / hybrid floor**; do not use it as loyalty linker score.
- Competitive narrative: graph + loyalty economics for rings; location compared to Incognia as enrichment only.
- C2/C7 status: **product posture fixed**; live Location score still gated by S1.

## Testing

1. Unit: relatedness emits with graph peers only → `relatedness_evidence` present; `geo_enrichment` empty/absent; deprecated `location_cohort_evidence` still present.
2. Unit: inference_build splits risks; `colocation_risk == max(...)`.
3. Evaluate contract: both keys on snapshot when signals present.
4. Frontend unit/test if existing patterns for flash cards; else minimal render test for Loyalty card when gates in audit.

## Claim language

- **OK:** “Location is optional enrichment; relatedness via graph; loyalty abuse via economics gates.”
- **Not OK:** “Location links related accounts” / equal Location pillar for loyalty maturity.

## Spec self-review

- [x] Dual-write explicit  
- [x] Impossible travel preserved  
- [x] Loyalty UI surfaces gates without claiming feeds always present  
- [x] No hard rename  
- [x] C2/C7 addressed without claiming S1 closed  
