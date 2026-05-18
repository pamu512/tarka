#!/usr/bin/env python3
"""Regenerate betterproto Python from proto/internal_comms.proto.

Requires: pip install "betterproto[compiler]" grpcio-tools
Run from repo root: python3 scripts/gen_internal_comms_py.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    proto = root / "proto" / "internal_comms.proto"
    out = root / "proto" / "gen" / "python"
    if not proto.is_file():
        print(f"missing proto: {proto}", file=sys.stderr)
        return 1
    gen_plugin = shutil.which("protoc-gen-python_betterproto")
    if gen_plugin is None:
        print(
            "protoc-gen-python_betterproto not on PATH. Install with:\n"
            '  pip install "betterproto[compiler]" grpcio-tools',
            file=sys.stderr,
        )
        return 1

    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{root / 'proto'}",
        f"--python_betterproto_out={out}",
        str(proto),
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=str(root), check=False)
    return int(r.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
