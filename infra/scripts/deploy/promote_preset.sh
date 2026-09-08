#!/usr/bin/env bash
# Promote a generated Helm preset values file through staging (local artifact copy + validation).
set -euo pipefail

PRESET="${1:?usage: promote_preset.sh <preset-name>}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

GENERATED="infra/deploy/generated/${PRESET}.values.yaml"
STAGING="infra/deploy/hosted/k8s/overlays/staging/${PRESET}.values.yaml"

GEN_ARGS=(
  --preset "$PRESET"
  --image-registry "${IMAGE_REGISTRY:-registry.example.com/tarka}"
  --db-url "${DATABASE_URL:-postgresql+asyncpg://fraud:pw@db.internal:5432/fraud}"
  --redis-url "${REDIS_URL:-redis://redis.internal:6379/0}"
  --output "$GENERATED"
)
if [[ "$PRESET" == "prod-on-k8s" ]]; then
  if [[ -z "${DIGEST_MAP:-}" ]]; then
    echo "FAIL: prod-on-k8s promote requires DIGEST_MAP=/path/to/image-digests.map (sha256 pins). Empty digest is not a grade." >&2
    exit 1
  fi
  GEN_ARGS+=(--digest-map "$DIGEST_MAP")
elif [[ -n "${DIGEST_MAP:-}" ]]; then
  GEN_ARGS+=(--digest-map "$DIGEST_MAP")
fi
python3 infra/scripts/deploy/generate_cloud_values.py "${GEN_ARGS[@]}"

mkdir -p "$(dirname "$STAGING")"
cp "$GENERATED" "$STAGING"

python3 infra/scripts/ci/cloud_preset_smoke.py

echo "Promoted $PRESET → $STAGING (review diff before kubectl apply)"
