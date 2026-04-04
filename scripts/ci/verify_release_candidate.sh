#!/usr/bin/env bash
# Release-candidate checks for v1.1.0: Investigation Copilot (investigation-agent) + frontend + TS SDK.
# Full repo lint (`ruff check .`) is the CI lint job; this script targets the copilot service and Node builds.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "== Ruff (investigation-agent only; matches copilot Python surface) =="
python -m ruff check services/investigation-agent
python -m ruff format --check services/investigation-agent

echo "== Frontend (npm ci + build) =="
(cd frontend && npm ci && npm run build)

echo "== Investigation agent (pytest) =="
(
  cd services/investigation-agent
  pip install -e ".[dev]" -q
  export PYTHONPATH="src:../shared"
  python -m pytest tests/ -q
)

echo "== TypeScript SDK build =="
(cd packages/fraud-sdk-typescript && npm ci && npm run build)

echo "verify_release_candidate.sh passed. For full matrix also confirm GitHub Actions ci.yml + security-scan.yml on the RC commit."
