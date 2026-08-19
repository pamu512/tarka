# Archived Compose files

Not the day-1 path. **Do not use for new work.** Advertised command:

```bash
docker compose \
  -f infra/deploy/docker-compose.lite.yml \
  -f infra/deploy/docker-compose.fraud-desk.yml \
  up --build
```

| File | Why archived |
|------|----------------|
| `docker-compose.lite.smoke.yml` | Superseded by `infra/deploy/docker-compose.lite.yml` |
| `docker-compose.single.yml` | same Lite path |
| `docker-compose.host-ports.override.yml` | broken vs current services |
| `docker-compose.streams-ai.yml` | quarantined `core_v2` speed-layer |
| `docker-compose.v2-ingest.yml` | ingest + Shadow lab rail |
| `docker-compose.demo-vertical.yml` | brochure / demo overlay |
| `docker-compose.graph-wire.yml` | lite `--profile graph` overlay |
| `docker-compose.sandbox.yml` | unused image-based sandbox |

## Canonical compose (stay under `infra/deploy/`)

1. **Desk / day-1:** `docker-compose.lite.yml` + `docker-compose.fraud-desk.yml`
2. **Local modular / profiles:** `docker-compose.yml` (`core`, `full`, `graph`, …)
3. **Production hardening overlay:** `docker-compose.production-hardening.yml`

Repo-root `docker-compose.yml` includes the desk pair so `docker compose up` is the front door.

Left in place (required CI / scripts still invoke the old path):

- `infra/deploy/docker-compose.graph-env.yml` — `full_stack_smoke.py`
- `infra/deploy/docker-compose.micro.yml` + `docker-compose.micro.e2e.yml` — ops-qa-desk / start-micro
- repo-root `docker-compose.local.yml` — optional Ollama overlay (not a second tree)
