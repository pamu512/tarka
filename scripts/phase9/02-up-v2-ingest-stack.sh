#!/usr/bin/env bash
# Phase 9 — start the v2 ingest stack in detached mode (default ports 8778, 8801, 8790).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
exec docker compose -f deploy/docker-compose.v2-ingest.yml up -d
