#!/usr/bin/env python3
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

"""Fail CI when frontend production build enables API mock mode."""
_TRUE_VALUES = {"1", "true", "yes", "on"}
_ASSIGN_RE = re.compile(r"^\s*VITE_USE_API_MOCKS\s*=\s*(.+?)\s*$")


def _is_true(raw: str) -> bool:
    v = raw.strip().strip("\"'").lower()
    return v in _TRUE_VALUES


def _scan_env_file(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        if _is_true(m.group(1)):
            return True
    return False


def main() -> int:
    env_value = os.environ.get("VITE_USE_API_MOCKS", "")
    if env_value and _is_true(env_value):
        print("ERROR: VITE_USE_API_MOCKS is true in build environment.", file=sys.stderr)
        return 1

    repo = Path(__file__).resolve().parents[2]
    frontend = repo / "frontend"
    candidates = sorted(frontend.glob(".env.production*")) + sorted(frontend.glob(".env*.production*"))
    bad = [str(p.relative_to(repo)) for p in candidates if _scan_env_file(p)]
    if bad:
        print("ERROR: VITE_USE_API_MOCKS=true found in production env files:", file=sys.stderr)
        for path in bad:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print("OK: frontend production mock-mode guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
