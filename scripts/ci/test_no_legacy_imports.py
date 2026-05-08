#!/usr/bin/env python3
"""
Fail CI if the legacy runtime protobuf package id (concatenation of ``tarka.evidence.`` and ``v1``)
appears outside explicitly allowlisted legacy surfaces.

Wire-format code must use ``tarka.evidence.wire.v1`` only, avoiding split-brain imports.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_FORBIDDEN_LEGACY_PKG = "tarka.evidence."
_FORBIDDEN_LEGACY_SUFFIX = "v1"
FORBIDDEN = _FORBIDDEN_LEGACY_PKG + _FORBIDDEN_LEGACY_SUFFIX

# Files that legitimately embed the legacy package name (compiled artifacts or legacy schemas).
_ALLOWLIST = frozenset(
    {
        "crates/tarka-core/proto/evidence.proto",
        "crates/tarka-core/src/evidence/mod.rs",
    }
)


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(out.stdout.strip())


def main() -> int:
    root = _repo_root()
    proc = subprocess.run(
        ["git", "grep", "-n", "--no-color", "-I", FORBIDDEN, "--", "."],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 1:
        return 0
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "")
        return proc.returncode

    violations: list[str] = []
    for line in proc.stdout.splitlines():
        path_str = line.split(":", 1)[0]
        normalized = path_str.replace("\\", "/").lstrip("./")
        if normalized not in _ALLOWLIST:
            violations.append(line)

    if violations:
        sys.stderr.write(
            f"Forbidden legacy protobuf package id {FORBIDDEN!r} "
            "found outside allowlisted legacy files:\n\n"
        )
        sys.stderr.write("\n".join(violations))
        sys.stderr.write("\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
