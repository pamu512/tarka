#!/usr/bin/env bash
# Optional load test using https://github.com/rakyll/hey
# Install: go install github.com/rakyll/hey@latest
# Usage: ./load-hey-evaluate.sh http://localhost:8000 2000 50
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
N="${2:-500}"
C="${3:-20}"
BODY='{"tenant_id":"load","event_type":"payment","entity_id":"load-entity","payload":{"amount":100}}'
if ! command -v hey >/dev/null 2>&1; then
  echo "hey not found; install with: go install github.com/rakyll/hey@latest"
  echo "Falling back to single curl (no load stats)."
  curl -s -o /dev/null -w "http_code=%{http_code} time=%{time_total}s\n" \
    -X POST "${BASE}/v1/decisions/evaluate" \
    -H "Content-Type: application/json" -d "$BODY"
  exit 0
fi
hey -n "$N" -c "$C" -m POST -T "application/json" -d "$BODY" "${BASE}/v1/decisions/evaluate"
