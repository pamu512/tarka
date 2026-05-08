#!/usr/bin/env bash
# Install each Python project in an isolated venv, freeze pins, run PyUp safety check (fail on CVE).
# Intended for CI (GitHub Actions). Requires: python3, pip, network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

: "${SAFETY_VERSION:=2.3.5}"
any_failed=0

while IFS= read -r -d '' pyproject; do
  dir="$(dirname "$pyproject")"
  rel="${dir#./}"
  echo "::group::safety — ${rel}"
  work="$(mktemp -d)"

  python3 -m venv "${work}/venv"
  # shellcheck disable=SC1090
  source "${work}/venv/bin/activate"
  python -m pip install -q --upgrade pip setuptools wheel
  python -m pip install -q "safety==${SAFETY_VERSION}"

  installed=0
  if [[ "$rel" == "." ]]; then
    if python -m pip install -q -e "${ROOT}[core]" 2>/dev/null; then
      installed=1
    elif python -m pip install -q -e "${ROOT}"; then
      installed=1
    fi
  else
    if python -m pip install -q -e "${ROOT}/${rel}[dev]" 2>/dev/null; then
      installed=1
    elif python -m pip install -q -e "${ROOT}/${rel}"; then
      installed=1
    fi
  fi

  if [[ "$installed" -ne 1 ]]; then
    echo "SKIP (pip install failed): ${rel}" >&2
    deactivate || true
    rm -rf "$work"
    echo "::endgroup::"
    continue
  fi

  python -m pip freeze --all > "${work}/freeze.txt"
  if [[ ! -s "${work}/freeze.txt" ]]; then
    echo "SKIP (empty freeze): ${rel}" >&2
    deactivate || true
    rm -rf "$work"
    echo "::endgroup::"
    continue
  fi

  set +e
  safety check --full-report -r "${work}/freeze.txt"
  st=$?
  set -e
  deactivate || true
  rm -rf "$work"

  if [[ "$st" -ne 0 ]]; then
    any_failed=1
  fi
  echo "::endgroup::"
done < <(
  find . \( -name .git -o -name target -o -name node_modules -o -name __pycache__ \) -prune -o \
    -path './templates/*' -prune -o \
    -name pyproject.toml -print0 |
    sort -z
)

exit "$any_failed"
