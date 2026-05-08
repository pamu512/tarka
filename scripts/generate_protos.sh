#!/usr/bin/env bash
# Generate Python protobuf + gRPC stubs + mypy stubs for every ``.proto`` under ``proto/``.
#
# Prerequisites (install into your active environment):
#   pip install grpcio-tools mypy-protobuf
# or, from ``crates/tarka-py``:
#   pip install -e ".[dev]"
#
# Usage (repository root):
#   ./scripts/generate_protos.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROTO_ROOT="${ROOT}/proto"
PYTHON_OUT="${ROOT}/crates/tarka-py/python"
PROTOC_PYTHON="${PROTOC_PYTHON:-python3}"

# Ensure grpc_tools / protoc-gen-mypy from the same interpreter are discoverable.
_PY_EXE="$("${PROTOC_PYTHON}" -c 'import sys; print(sys.executable)')"
_PY_BINDIR="$(dirname "${_PY_EXE}")"
export PATH="${_PY_BINDIR}:${PATH}"

if [[ ! -d "${PROTO_ROOT}" ]]; then
  echo "error: missing proto directory: ${PROTO_ROOT}" >&2
  exit 1
fi

PROTO_FILES=()
while IFS= read -r -d '' f; do
  PROTO_FILES+=("$f")
done < <(find "${PROTO_ROOT}" -name '*.proto' -print0 | LC_ALL=C sort -z)
if [[ "${#PROTO_FILES[@]}" -eq 0 ]]; then
  echo "error: no .proto files under ${PROTO_ROOT}" >&2
  exit 1
fi

if ! "${PROTOC_PYTHON}" -c "import grpc_tools.protoc" 2>/dev/null; then
  echo "error: grpc_tools not importable with ${PROTOC_PYTHON}; install grpcio-tools (see crates/tarka-py pyproject optional dev)." >&2
  exit 1
fi

if ! command -v protoc-gen-mypy >/dev/null 2>&1; then
  echo "error: protoc-gen-mypy not found next to ${PROTOC_PYTHON}; install mypy-protobuf in that environment." >&2
  echo "hint: (repo root) pip install -e \"crates/tarka-py[dev]\"" >&2
  exit 1
fi

mkdir -p "${PYTHON_OUT}"

"${PROTOC_PYTHON}" -m grpc_tools.protoc \
  -I "${PROTO_ROOT}" \
  --python_out="${PYTHON_OUT}" \
  --grpc_python_out="${PYTHON_OUT}" \
  --mypy_out="${PYTHON_OUT}" \
  "${PROTO_FILES[@]}"

echo "Generated Python protobuf / gRPC / mypy stubs into: ${PYTHON_OUT}"
