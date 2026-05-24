#!/usr/bin/env bash
# Run Epic C Release Candidate gates locally (see docs/docs/guides/counter-replay-parity.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RC_SHA="$(git -C "$ROOT" rev-parse HEAD)"
EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT/docs/docs/releases/evidence/v1.2.0-epic-c}"
mkdir -p "$EVIDENCE_DIR"
LOG="$EVIDENCE_DIR/rc-gates-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1

echo "=== Epic C RC gates ==="
echo "RC_SHA=$RC_SHA"
echo "AGG_KEY_VERSION=${AGG_KEY_VERSION:-local_v1}"
export AGG_KEY_VERSION="${AGG_KEY_VERSION:-local_v1}"

echo "--- C-3c: test_golden_counters.py ---"
(
  cd "$ROOT/services/decision-api"
  PYTHONPATH=src:tests python3 -m pytest tests/test_golden_counters.py tests/test_counter_manifest.py tests/test_day60_velocity_windows.py tests/test_challenge_policy.py -q --tb=short
)

echo "--- C-3a: weekly parity runbook (requires redis on 6379) ---"
if command -v redis-cli >/dev/null 2>&1 && redis-cli -u "${REDIS_URL:-redis://127.0.0.1:6379/0}" ping 2>/dev/null | grep -q PONG; then
  python3 "$ROOT/scripts/replay/replay_aggregates.py" \
    --input "$ROOT/scripts/replay/fixtures/parity_smoke.jsonl" \
    --redis-url redis://127.0.0.1:6379/14
  python3 "$ROOT/scripts/replay/replay_aggregates.py" \
    --input "$ROOT/scripts/replay/fixtures/parity_smoke.jsonl" \
    --redis-url redis://127.0.0.1:6379/15
  python3 "$ROOT/scripts/replay/diff_aggregate_redis.py" \
    --left-url redis://127.0.0.1:6379/14 \
    --right-url redis://127.0.0.1:6379/15 \
    --pattern 'fraud:agg*'
  echo "C-3a manual parity: PASS"
else
  echo "SKIP C-3a: Redis not reachable — run counter-parity-smoke workflow on RC or start local Redis"
fi

echo "--- C-4: feature-service day60 tests ---"
(
  cd "$ROOT/services/feature-service"
  PYTHONPATH="$ROOT/services/shared/src:$ROOT/services/decision-api/tests:$ROOT/services/feature-service/src" \
    python3 -m pytest tests/test_velocity_day60_parity.py tests/test_shared_velocity.py -q --tb=short
)

echo "Log written: $LOG"
echo "Attach this log plus staging cutover log (gate C-2) to the v1.2.0 release evidence bundle."
