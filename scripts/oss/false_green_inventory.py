#!/usr/bin/env python3
"""Ratchet: known false-green lie shapes must not reappear.

Allowlist stays empty. A new hit fails CI. Do not add a path unless the
match is not a lie (and then shrink it again as soon as the line moves).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

# Empty on purpose. Path relative to repo root.
ALLOWLIST: frozenset[str] = frozenset()

GETSOURCE = re.compile(r"inspect\.getsource")
SCORE_DEFAULT_ZERO = re.compile(r"""\.get\(\s*['\"]score['\"]\s*,\s*0""")
_SKIP_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git"}


def _rel(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _iter_py() -> list[Path]:
    out: list[Path] = []
    for path in _REPO.rglob("*.py"):
        if _SKIP_DIRS.intersection(path.parts):
            continue
        out.append(path)
    return out


def _is_test(rel: str) -> bool:
    return "/tests/" in f"/{rel}" or rel.startswith("tests/")


def main() -> int:
    hits: list[str] = []
    for path in _iter_py():
        rel = _rel(path)
        if rel in ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        if _is_test(rel) and GETSOURCE.search(text):
            hits.append(f"{rel}: inspect.getsource (string-gate test)")
        if rel.startswith("services/") and not _is_test(rel) and SCORE_DEFAULT_ZERO.search(text):
            hits.append(f"{rel}: .get(\"score\", 0) invents a score")

    stale = sorted(p for p in ALLOWLIST if not (_REPO / p).is_file())
    if stale:
        hits.append("allowlist paths missing: " + ", ".join(stale))

    if hits:
        print("false_green_inventory: FAIL", file=sys.stderr)
        for hit in hits:
            print(f"  - {hit}", file=sys.stderr)
        return 1
    print("false_green_inventory: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
