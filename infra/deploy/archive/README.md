# Archived Compose files

Pre–`core-api` consolidation artifacts. **Do not use for new work.**

| File | Superseded by |
|------|----------------|
| `docker-compose.lite.smoke.yml` | `infra/deploy/docker-compose.lite.yml` (+ root `docker-compose.yml` include) |
| `docker-compose.single.yml` | same Lite path |
| `docker-compose.host-ports.override.yml` | broken vs current services; use Lite / main deploy ports |

## Canonical compose entrypoints

1. **Default local:** repo-root `docker-compose.yml` → Lite (`core-api` / decision-api)
2. **Modular / profiles:** `infra/deploy/docker-compose.yml` (`core`, `full`, `graph`, …)
3. **V2 ingest rail:** `infra/deploy/docker-compose.v2-ingest.yml`
4. **Legacy streams (`core_v2`):** `docker-compose.streams-ai.yml` (quarantined)

Overlays that stay live (not archived): `docker-compose.local.yml`, `demo-vertical`, `micro`, `sandbox`, `production-hardening`, observability addon, local-ai addons, ai-governance overrides, janusgraph demo.
