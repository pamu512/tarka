# Plan: P0/P1 Competitive Gaps (2026-08-07)

## Files

| Area | Touch |
|---|---|
| P0-CC | `champion_challenger_audit.py`, `calibration_api.py`, `OpsShadow.tsx`, `client.ts`, tests |
| P0-L2 | `partner_fusion_status.py`, ops endpoint, `Integrations.tsx`, OpenSanctions catalog note |
| P1-FSC | `docs/docs/guides/feature-serving-contract.md`, feature-service contract GET, FeatureTools banner |
| P1-hot | loyalty bridge timeout/circuit, `auth-vs-forensics-path.md`, evaluation-posture fields |
| P1-typ | `typology.py` telemetry helper, admin GET, OpsShadow or small typology panel |

## Tasks

1. P0-CC pure aggregate + label-gated promote → API → OpsShadow  
2. P0-L2 status parse + GET + Integrations panel  
3. P1-FSC contract endpoint + doc + FeatureTools link  
4. P1-hot circuit/timeout + SLO on posture + doc  
5. P1-typ weighted telemetry endpoint + UI hook  
6. Verify tests; push if prior pattern
