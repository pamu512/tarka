#!/usr/bin/env bash
# Smoke: build/install local SDKs (registry publish is separate CI with provenance).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Python SDK =="
python3 -m pip install -q -e "${ROOT}/packages/fraud-sdk-python"
python3 -c "import fraud_stack_sdk; print('tarka-sdk import ok')"

echo "== TypeScript SDK =="
(cd "${ROOT}/packages/fraud-sdk-typescript" && npm ci --ignore-scripts && npm run build && npm test)

echo "SDK smoke OK"
