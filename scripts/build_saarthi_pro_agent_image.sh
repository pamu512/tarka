#!/usr/bin/env bash
# Build Saarthi Pro agent image from fraud-stack repo root (Linux/macOS CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="${SAARTHI_PRO_VERSION:-0.1.0}"
SHA="${FRAUD_STACK_GIT_SHA:-$(git rev-parse HEAD)}"
CONTRACT="${INTEGRATION_CONTRACT_VERSION:-1.1.0}"
docker build -f distributions/saarthi-pro-agent/Dockerfile \
  --build-arg "SAARTHI_PRO_VERSION=${VER}" \
  --build-arg "FRAUD_STACK_GIT_SHA=${SHA}" \
  --build-arg "INTEGRATION_CONTRACT_VERSION=${CONTRACT}" \
  -t "saarthi-pro-agent:${VER}" .
echo "Built saarthi-pro-agent:${VER} (fraud-stack ${SHA}, contract ${CONTRACT})"
