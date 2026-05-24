#!/usr/bin/env bash
# Deprecate the NATS shadow.investigate worker when async REVIEW handoff is unused.
#
# Prefer synchronous ``POST /v1/analyze`` from the orchestrator ingest path (SHADOW_REVIEW /
# elevated FLAG triage). Run this only after confirming no deployment subscribes to
# ``shadow.investigate`` or publishes REVIEW jobs to NATS.
#
# Usage:
#   ./scripts/shadow/deprecate_nats_shadow_investigate_worker.sh [--apply]
#
# Without --apply: prints planned removals (dry run).
# With --apply: deletes the worker module and strips optional NATS REVIEW dispatch.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

WORKER="tarka_v2_core/services/shadow_agent/src/shadow_agent/workers/nats_shadow_investigate.py"
RUNTIME="tarka_v2_core/services/shadow_agent/src/shadow_agent/workers/runtime.py"
TEST="tarka_v2_core/services/shadow_agent/tests/test_nats_shadow_investigate_worker.py"
DISPATCH="tarka_v2_core/services/orchestrator/src/orchestrator/queues/shadow_dispatch.py"

echo "=== NATS shadow.investigate deprecation (dry_run=$((1-APPLY))) ==="
echo
echo "Will remove:"
echo "  - ${WORKER}"
echo "  - ${RUNTIME}"
echo "  - ${TEST}"
echo
echo "Will edit (manual follow-up if --apply):"
echo "  - ${DISPATCH} — remove dispatch_shadow_investigate_if_review and NATS publish from transaction_ingest"
echo "  - orchestrator/main.py — remove shadow_dispatch_nats lifecycle"
echo "  - tarka_v2_core/services/shadow_agent/pyproject.toml — drop [project.optional-dependencies].worker if unused"
echo
echo "Verify no references:"
echo "  rg 'nats_shadow_investigate|shadow\\.investigate|shadow_dispatch_nats' \"${ROOT}\""
echo

if [[ "${APPLY}" -eq 0 ]]; then
  echo "Re-run with --apply to delete worker files."
  exit 0
fi

rm -f "${ROOT}/${WORKER}" "${ROOT}/${RUNTIME}" "${ROOT}/${TEST}"
echo "Deleted worker, runtime, and test."
echo "Complete orchestrator NATS dispatch removal manually (see list above)."
