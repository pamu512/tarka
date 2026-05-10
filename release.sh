#!/usr/bin/env bash
# Wrapper so you can run: ./release.sh 1.0.0-beta.1
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${ROOT}/scripts/release.sh" "$@"
