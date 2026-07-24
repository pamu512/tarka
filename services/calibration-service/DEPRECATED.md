# Calibration package — deploy via signal-api (canonical)

**Runtime owner:** `signal-api` mount at `/calibration`  
(`http://signal-api:8000/calibration` or `:8004` depending on compose port map).

Decision-api reaches scoring/drift through `CALIBRATION_SERVICE_URL`
(default `http://signal-api:8000/calibration` / `:8004/calibration`). Appends
`/v1/score` and `/v1/drift`.

This directory is the **library + optional standalone image**. Prefer the
embedded sub-app in `services/signal-api` (Dockerfile copies this package).

## Standalone image / Helm

`infra/deploy/helm/fraud-stack` template `calibration-service.yaml` stays
**disabled** (`calibrationService.enabled: false`). Enabling it alone does
**not** retarget `CALIBRATION_SERVICE_URL` — you would get an unwired pod
(Helm port historically 8013 vs Dockerfile 8011).

Use standalone only for split-scale experiments, and set
`CALIBRATION_SERVICE_URL` explicitly to that Service.

## Not this package

Decision-api also exposes local ops routes under `/v1/calibration/*`
(reliability CSV, audit-backed bins). Those stay on decision-api; they are
not the remote `CALIBRATION_SERVICE_URL` scorer.
