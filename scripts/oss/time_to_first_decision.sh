#!/usr/bin/env bash
# Time-to-first-decision: fresh clone -> make doctor -> first receipt.
# Measures the onboarding funnel the desk ships (G7). Run on a quiet machine;
# needs Docker running and free ports (TARKA_PG_PORT remap honored).
#
#   ./scripts/oss/time_to_first_decision.sh [workdir]
#
# Output: stage durations + total, machine-readable last line:
#   TTFD_JSON={"clone_s":..,"doctor_s":..,"demo_s":..,"first_receipt_s":..,"total_s":..}

set -euo pipefail

ROOT="${1:-$(mktemp -d /tmp/ttfd-XXXXXX)}"
MARK=$(date +%s)
stage() { # name
  local now=$(date +%s)
  local d=$((now - MARK))
  echo "  [$d s] $1"
}

echo "time-to-first-decision -> $ROOT"
mkdir -p "$ROOT"

# Stage 1: clone (shallow keeps it about fetch, not history)
MARK=$(date +%s)
git clone --depth 1 https://github.com/pamu512/tarka.git "$ROOT/tarka" > /dev/null 2>&1
CLONE_S=$(($(date +%s) - MARK))
stage "clone done (${CLONE_S}s)"

# Stage 2: doctor
MARK=$(date +%s)
(cd "$ROOT/tarka" && TARKA_PG_PORT="${TARKA_PG_PORT:-15432}" make doctor > /dev/null)
DOCTOR_S=$(($(date +%s) - MARK))
stage "doctor ok (${DOCTOR_S}s)"

# Stage 3: demo up + first receipt (demo waits for health, posts events)
MARK=$(date +%s)
(cd "$ROOT/tarka" && TARKA_PG_PORT="${TARKA_PG_PORT:-15432}" make demo > "$ROOT/demo.log" 2>&1)
DEMO_S=$(($(date +%s) - MARK))
stage "demo + first receipts (${DEMO_S}s)"

TOTAL_S=$((CLONE_S + DOCTOR_S + DEMO_S))
echo
echo "clone=${CLONE_S}s doctor=${DOCTOR_S}s demo(first receipts)=${DEMO_S}s total=${TOTAL_S}s"
echo "TTFD_JSON={\"clone_s\":$CLONE_S,\"doctor_s\":$DOCTOR_S,\"demo_s\":$DEMO_S,\"total_s\":$TOTAL_S}"
