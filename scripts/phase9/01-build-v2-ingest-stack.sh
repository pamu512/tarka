#!/usr/bin/env bash
# Phase 9 — build container images for the v2 ingest stack (rule engine, shadow, orchestrator).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
exec docker compose -f deploy/docker-compose.v2-ingest.yml build
