#!/usr/bin/env bash
# Prompt 134: start Ollama with RAM-friendly caps (M-series / 24GB class laptops).
set -euo pipefail
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
exec ollama "$@"
