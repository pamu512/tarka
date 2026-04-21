# Local chaos exercises (Docker Compose)

Use these steps on a **non-production** machine to validate degradation paths, SLO surfaces, and operator instincts. Always coordinate if you share a host with teammates.

**Related:** [Chaos runbook template](../../docs/docs/guides/runbook-chaos-template.md) (copy for a real incident or game day).

## Prerequisites

- Repo root as working directory for paths below.
- Stack up with at least **`core`** (and optionally **`streaming`**, **`graph`**, **`ml`**) profiles — see `deploy/docker-compose.yml` header comments.

Example (core only):

```bash
cd deploy
docker compose -f docker-compose.yml --profile core up -d --build
```

## Safety

- Do **not** run stop/kill against shared staging/prod clusters without a change window.
- Prefer **`docker compose stop <service>`** over `docker rm` so recovery is `start` + health wait.
- After each exercise, confirm **`docker compose ps`** is healthy before the next fault.

## Fault matrix (suggested order)

| Fault | Command (from `deploy/`) | What to watch |
|-------|---------------------------|---------------|
| **Redis unavailable** | `docker compose -f docker-compose.yml stop redis` | Decision API velocity / aggregate paths; `GET http://localhost:8000/v1/slo` (if wired); UI readiness strip if using the analyst banner. |
| **Postgres unavailable** | `docker compose -f docker-compose.yml stop postgres` | Decision API should fail closed or error clearly; no silent success. |
| **NATS unavailable** (needs `--profile streaming` or `full`) | `docker compose -f docker-compose.yml stop nats` | Ingest / streaming consumers; DLQ behavior per your profile. |

Recovery (example):

```bash
docker compose -f docker-compose.yml start redis
docker compose -f docker-compose.yml ps
```

## Observation checklist

- **HTTP:** `curl -sf http://localhost:8000/v1/health` (decision-api on `8000`).
- **SLO / degradation:** `GET /v1/slo` on services that expose it (see `docs/docs/guides/service-slos-v1.md`).
- **Logs:** `docker compose -f docker-compose.yml logs -f decision-api --tail=80` during the fault window.

## CI / automation (R4.2)

- **Script:** `scripts/chaos/chaos_smoke.py` — baseline recovery path (`redis` or `postgres`) plus optional dependency fallback matrix checks (`graph-service`, `feature-service`, `ml-scoring`, `counter-service`, `location-service`, `calibration-service`) that assert evaluate remains `200` with expected `fallback_reason` fragments.
- **GitHub Actions:** workflow **`chaos-smoke`** (manual dispatch only) in `.github/workflows/chaos-smoke.yml`. Choose profile (`core`/`full`), fault service, and whether to run dependency fallback checks.

```bash
python3 scripts/chaos/chaos_smoke.py
python3 scripts/chaos/chaos_smoke.py --fault postgres --wait-health-seconds 600
python3 scripts/chaos/chaos_smoke.py --profile full --dependency-fallback-checks
```

See also **R4** in `docs/docs/guides/v1.2.5-execution-backlog-resiliency-etl-rules.md`.
