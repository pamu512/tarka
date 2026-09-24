#!/usr/bin/env bash
# Scheduled calibration label snapshots + drift computation (R12/G3).
# OpsCalibration renders drift_flag; this loop feeds it: on each tick it
# snapshots live label joins for each configured tenant (as an integrity
# histogram snapshot) and reads back the drift hint so the tick log shows
# what the desk will render.
#
# Usage (repo root):
#   DECISION_API_URL=http://127.0.0.1:8000 CALIBRATION_TICK_TENANTS=acme \
#     ./scripts/calibration_tick_loop.sh
set -euo pipefail

BASE="${DECISION_API_URL:-http://127.0.0.1:8000}"
INTERVAL="${CALIBRATION_TICK_INTERVAL_S:-3600}"
TENANTS="${CALIBRATION_TICK_TENANTS:-}"
API_KEY="${API_KEYS:-}"
API_KEY="${API_KEY%%,*}"

echo "calibration_tick base=${BASE} interval=${INTERVAL}s tenants=${TENANTS:-<unset>}"

snapshot_tenant() {
  local tenant="$1"
  # Pull loop-metrics join (label states over the receipt window) and shape it
  # into a CalibrationSnapshotIn: bound vs pending becomes the integrity
  # histogram; sample_count = receipts in window.
  local metrics histogram sample_count
  metrics=$(curl -sS -m 55 "${BASE%/}/decisions/v1/observe/loop-metrics?tenant_id=${tenant}" \
    ${API_KEY:+-H "x-api-key: ${API_KEY}"} || echo '{}')
  local parsed
  parsed=$(printf '%s' "${metrics}" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
labeled = int(d.get("labeled_receipt_count") or 0)
receipts = int(d.get("receipt_count") or 0)
hist = {"labeled": labeled, "unlabeled": max(receipts - labeled, 0)}
print(json.dumps({"hist": hist, "n": max(receipts, 1)}))
' 2>/dev/null || echo '{"hist":{"labeled":0,"unlabeled":1},"n":1}')
  histogram=$(printf '%s' "${parsed}" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["hist"]))')
  sample_count=$(printf '%s' "${parsed}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["n"])')
  local body
  body=$(python3 -c '
import json, sys
hist = json.loads(sys.argv[1])
print(json.dumps({
    "tenant_id": sys.argv[2],
    "profile": "default",
    "sample_count": int(sys.argv[3]),
    "integrity_histogram": hist,
    "notes": "calibration_tick",
}))
' "${histogram:-{\}}" "${tenant}" "${sample_count:-1}" 2>/dev/null || printf '{"tenant_id":"%s","profile":"default","sample_count":1,"integrity_histogram":{},"notes":"calibration_tick"}' "${tenant}")
  curl -sS -m 30 -X POST "${BASE%/}/decisions/v1/calibration/snapshots" \
    -H "Content-Type: application/json" \
    ${API_KEY:+-H "x-api-key: ${API_KEY}"} \
    -d "${body}" || true
  echo
  curl -sS -m 30 "${BASE%/}/decisions/v1/calibration/drift?tenant_id=${tenant}" \
    ${API_KEY:+-H "x-api-key: ${API_KEY}"} || true
  echo
}

while true; do
  if [[ -n "${TENANTS}" ]]; then
    IFS=',' read -ra list <<< "${TENANTS}"
    for t in "${list[@]}"; do
      [[ -n "${t}" ]] && snapshot_tenant "${t}"
    done
  else
    echo "calibration_tick: CALIBRATION_TICK_TENANTS unset - nothing to do"
  fi
  sleep "${INTERVAL}"
done
