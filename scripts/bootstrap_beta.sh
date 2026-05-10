#!/usr/bin/env bash
# Beta tester entry point: strict checks for Docker, Compose, Python 3.11+,
# basic RAM, and local Ollama + baseline model (llama3.2 or qwen3-vl:30b) before sidecars start.
#
# Usage:
#   ./scripts/bootstrap_beta.sh              # verify only
#   ./scripts/bootstrap_beta.sh --launch   # verify then `docker compose up -d`
#
# Ollama:
#   - Probes GET http://localhost:11434/api/tags (override base with OLLAMA_BASE).
#   - Accepts any model whose name starts with llama3.2 or equals qwen3-vl:30b (tag suffix OK).
#   - If neither is present and Ollama responds, runs: ollama run llama3.2 (see ensure_ollama_baseline).
#
# Test hooks (gate / CI):
#   BOOTSTRAP_OLLAMA_TAGS_JSON='{"models":[]}'  # skip curl; parse this JSON instead
#   BOOTSTRAP_OLLAMA_PULL_DRY_RUN=1            # log pull command but do not execute ollama
#   BOOTSTRAP_ONLY_OLLAMA=1                    # skip Docker/Python/RAM; run Ollama baseline block only
#
# shellcheck disable=SC3040  # we require bash for pipefail

set -e
set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

fatal() {
  printf '%b%b%b\n' "${RED}" "${BOLD}" "[bootstrap_beta] ERROR${NC}" >&2
  printf '%b%s%b\n' "${RED}" "$1" "${NC}" >&2
  exit 1
}

warn() {
  printf '%b%b%s%b\n' "${YELLOW}" "${BOLD}" "[bootstrap_beta] WARN" "${NC}" >&2
  printf '%b%s%b\n' "${YELLOW}" "$1" "${NC}" >&2
}

info() {
  printf '%b%s\n' "${GREEN}[bootstrap_beta]${NC} " "$1"
}

detect_os() {
  case "$(uname -s)" in
    Darwin) echo "darwin" ;;
    Linux) echo "linux" ;;
    *) echo "other" ;;
  esac
}

install_hint_docker() {
  local os
  os="$(detect_os)"
  case "$os" in
    darwin)
      printf '%s\n' "  brew install --cask docker"
      printf '%s\n' "  open -a Docker   # start Docker Desktop, wait until running"
      ;;
    linux)
      printf '%s\n' "  curl -fsSL https://get.docker.com | sudo sh"
      printf '%s\n' "  sudo usermod -aG docker \"\$USER\" && newgrp docker   # optional: run without sudo"
      ;;
    *)
      printf '%s\n' "  https://docs.docker.com/get-docker/"
      ;;
  esac
}

install_hint_compose() {
  local os
  os="$(detect_os)"
  case "$os" in
    darwin)
      printf '%s\n' "  # Docker Desktop includes: docker compose"
      printf '%s\n' "  brew install --cask docker"
      ;;
    linux)
      printf '%s\n' "  sudo apt-get update && sudo apt-get install -y docker-compose-plugin"
      printf '%s\n' "  # or: sudo dnf install docker-compose-plugin"
      ;;
    *)
      printf '%s\n' "  https://docs.docker.com/compose/install/linux/"
      ;;
  esac
}

install_hint_python() {
  local os
  os="$(detect_os)"
  case "$os" in
    darwin)
      printf '%s\n' "  brew install python@3.12"
      ;;
    linux)
      printf '%s\n' "  sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv"
      printf '%s\n' "  # or: sudo dnf install python3.12"
      ;;
    *)
      printf '%s\n' "  Install Python 3.11+ from https://www.python.org/downloads/"
      ;;
  esac
}

require_docker_cli() {
  if ! command -v docker >/dev/null 2>&1; then
    fatal "$(printf '%s\n\n%s\n%s\n' \
      "Docker CLI is not on PATH (Docker not installed or PATH misconfigured)." \
      "Install Docker, then re-run this script. Example commands for your OS:" \
      "$(install_hint_docker)")"
  fi
}

require_docker_daemon() {
  if ! docker info >/dev/null 2>&1; then
    fatal "$(printf '%s\n\n%s\n%s\n' \
      "Docker is installed but the daemon is not reachable (is Docker Desktop / dockerd running?)." \
      "Start Docker, then re-run. On macOS after brew install:" \
      "  open -a Docker")"
  fi
}

require_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
    return 0
  fi
  fatal "$(printf '%s\n\n%s\n%s\n' \
    "Neither \`docker compose\` (v2 plugin) nor \`docker-compose\` (v1) is available." \
    "Install the Compose plugin or standalone docker-compose. Examples:" \
    "$(install_hint_compose)")"
}

pick_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        printf '%s' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

require_python() {
  if ! PYTHON_BIN="$(pick_python)"; then
    fatal "$(printf '%s\n\n%s\n%s\n' \
      "Python 3.11 or newer is required but no suitable interpreter was found (tried python3.13, python3.12, python3.11, python3)." \
      "Install Python 3.11+, then re-run. Example commands:" \
      "$(install_hint_python)")"
  fi
  export PYTHON_BIN
}

ram_gib() {
  local os raw
  os="$(detect_os)"
  case "$os" in
    darwin)
      raw="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
      awk -v b="$raw" 'BEGIN { printf "%.1f", b/1024/1024/1024 }'
      ;;
    linux)
      awk '/MemTotal:/ { printf "%.1f", $2/1024/1024 }' /proc/meminfo 2>/dev/null || echo "0"
      ;;
    *)
      echo "0"
      ;;
  esac
}

check_hardware() {
  local gib
  gib="$(ram_gib)"
  if awk -v g="$gib" 'BEGIN { if (g <= 0 || g < 4) exit 0; exit 1 }'; then
    fatal "$(printf '%s\n' "Reported RAM is ${gib} GiB; beta stack expects at least ~4 GiB for Docker.")"
  fi
  if awk -v g="$gib" 'BEGIN { if (g < 8) exit 0; exit 1 }'; then
    warn "RAM is about ${gib} GiB; 8+ GiB is recommended for Postgres + Redis + sidecars."
  fi
}

# Default matches operator docs / Prompt 65 (localhost + standard Ollama port).
OLLAMA_BASE="${OLLAMA_BASE:-http://localhost:11434}"

ollama_tags_json_live() {
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl not found; cannot probe Ollama /api/tags. Install curl."
    printf ''
    return 1
  fi
  curl -s --max-time "${OLLAMA_CURL_TIMEOUT:-10}" "${OLLAMA_BASE}/api/tags"
}

ollama_tags_json() {
  if [[ -n "${BOOTSTRAP_OLLAMA_TAGS_JSON:-}" ]]; then
    printf '%s' "${BOOTSTRAP_OLLAMA_TAGS_JSON}"
    return 0
  fi
  ollama_tags_json_live
}

ollama_json_has_baseline_model() {
  local json="$1"
  if [[ -z "$json" ]]; then
    return 1
  fi
  if command -v jq >/dev/null 2>&1; then
    jq -e '(.models // []) | map(.name) | any(test("^llama3\\.2") or test("^qwen3-vl:30b"))' <<<"$json" >/dev/null 2>&1
    return
  fi
  grep -qE '"name"[[:space:]]*:[[:space:]]*"(llama3\.2|qwen3-vl:30b)' <<<"$json"
}

ensure_ollama_baseline_model() {
  local tags_json
  tags_json="$(ollama_tags_json)" || true
  if [[ -z "$tags_json" ]]; then
    warn "No JSON from ${OLLAMA_BASE}/api/tags (Ollama not running?). Skipping baseline model check."
    return 0
  fi
  if ! grep -q '"models"' <<<"$tags_json" 2>/dev/null; then
    warn "Ollama /api/tags response did not look like JSON with models[]; skipping baseline check."
    return 0
  fi

  if ollama_json_has_baseline_model "$tags_json"; then
    info "Ollama baseline satisfied: found llama3.2* or qwen3-vl:30b in /api/tags."
    return 0
  fi

  warn "Ollama is up but no llama3.2 or qwen3-vl:30b in /api/tags; installing baseline via ollama run llama3.2 …"
  if ! command -v ollama >/dev/null 2>&1; then
    fatal "$(printf '%s\n\n%s\n' \
      "ollama CLI is not on PATH; cannot run baseline model install." \
      "Install Ollama from https://ollama.com then re-run this script.")"
  fi
  if [[ -n "${BOOTSTRAP_OLLAMA_PULL_DRY_RUN:-}" ]]; then
    info "BOOTSTRAP_OLLAMA_PULL_DRY_RUN=1 → would run: ollama run llama3.2"
    return 0
  fi
  # Non-interactive: `ollama run` pulls if missing then loads a REPL; send /bye to exit.
  if ! printf '/bye\n' | ollama run llama3.2; then
    fatal "$(printf '%s\n' "ollama run llama3.2 failed (see stderr above). Try: ollama pull llama3.2")"
  fi
  # Re-check against the real daemon (ignore BOOTSTRAP_OLLAMA_TAGS_JSON stub).
  tags_json="$(ollama_tags_json_live)" || true
  if ! ollama_json_has_baseline_model "$tags_json"; then
    fatal "$(printf '%s\n' "After ollama run llama3.2, /api/tags still shows no llama3.2 or qwen3-vl:30b.")"
  fi
  info "Baseline model is now present per /api/tags."
}

do_launch() {
  local compose_file
  compose_file="${DOCKER_COMPOSE_FILE:-docker-compose.yml}"
  if [[ ! -f "${ROOT}/${compose_file}" ]]; then
    fatal "Compose file not found: ${ROOT}/${compose_file} (set DOCKER_COMPOSE_FILE to override)."
  fi
  info "Starting stack from ${compose_file} …"
  (cd "${ROOT}" && "${COMPOSE[@]}" -f "${compose_file}" up -d)
  info "Compose up finished. Use: ${COMPOSE[*]} -f ${compose_file} ps"
}

main() {
  local launch=0
  if [[ "${1:-}" == "--launch" ]]; then
    launch=1
  fi

  if [[ -n "${BOOTSTRAP_ONLY_OLLAMA:-}" ]]; then
    ensure_ollama_baseline_model
    exit 0
  fi

  # Docker before Python so a stripped PATH surfaces "install Docker" first (beta gate).
  require_docker_cli
  require_docker_daemon
  require_compose
  require_python
  check_hardware
  ensure_ollama_baseline_model

  info "Dependency checks passed (python: ${PYTHON_BIN}, compose: ${COMPOSE[*]})."
  if [[ "$launch" -eq 1 ]]; then
    do_launch
  else
    info "Verify-only mode. To start sidecars: ${BOLD}$0 --launch${NC}"
  fi
}

main "$@"
