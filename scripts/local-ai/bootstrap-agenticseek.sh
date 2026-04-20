#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy/local-ai/.env.local}"
EXAMPLE_FILE="$ROOT/deploy/local-ai/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  python3 - "$ENV_FILE" <<'PY'
import secrets
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
lines = env_path.read_text(encoding="utf-8").splitlines()
updated = []
for line in lines:
    if line.startswith("SEARXNG_SECRET_KEY="):
        updated.append(f"SEARXNG_SECRET_KEY={secrets.token_hex(24)}")
    elif line.startswith("N8N_ENCRYPTION_KEY="):
        updated.append(f"N8N_ENCRYPTION_KEY={secrets.token_hex(24)}")
    else:
        updated.append(line)
env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
fi

set -a
source "$ENV_FILE"
set +a

if [[ "${AGENTICSEEK_DIR:-}" == *"\$USER"* ]]; then
  AGENTICSEEK_DIR="${AGENTICSEEK_DIR/\$USER/$USER}"
fi

mkdir -p "$(dirname "$AGENTICSEEK_DIR")"

if [[ -d "$AGENTICSEEK_DIR/.git" ]]; then
  git -C "$AGENTICSEEK_DIR" fetch --depth 1 origin "${AGENTICSEEK_REF:-main}"
  git -C "$AGENTICSEEK_DIR" checkout -f "${AGENTICSEEK_REF:-main}"
  git -C "$AGENTICSEEK_DIR" pull --ff-only origin "${AGENTICSEEK_REF:-main}"
else
  git clone --depth 1 --branch "${AGENTICSEEK_REF:-main}" \
    https://github.com/Fosowl/agenticSeek.git "$AGENTICSEEK_DIR"
fi

python3 - "$AGENTICSEEK_DIR/config.ini" "${OLLAMA_BASE_URL}" "${OLLAMA_MODEL}" <<'PY'
import configparser
import sys

config_path, ollama_base, ollama_model = sys.argv[1], sys.argv[2], sys.argv[3]
provider_addr = ollama_base.replace("http://", "").replace("https://", "")
provider_addr = provider_addr.rstrip("/")

config = configparser.ConfigParser()
config.read(config_path, encoding="utf-8")

if "MAIN" not in config:
    config["MAIN"] = {}
if "BROWSER" not in config:
    config["BROWSER"] = {}

config["MAIN"]["is_local"] = "True"
config["MAIN"]["provider_name"] = "ollama"
config["MAIN"]["provider_model"] = ollama_model
config["MAIN"]["provider_server_address"] = provider_addr
config["BROWSER"]["headless_browser"] = "True"

with open(config_path, "w", encoding="utf-8") as handle:
    config.write(handle)
PY

echo "AgenticSeek is ready at: $AGENTICSEEK_DIR"
echo "Environment file: $ENV_FILE"
