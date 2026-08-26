#!/usr/bin/env bash
# Leftover root wrapper. Canonical: scripts/release.sh 1.0.0-beta.1
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/release.sh" "$@"
