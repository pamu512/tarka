#!/usr/bin/env python3
"""Guard against import/path-style regressions in Python services."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "services"


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in SERVICES_DIR.rglob("*.py"):
        rel = path.relative_to(SERVICES_DIR)
        if any(part in {".venv", "venv", "__pycache__", "site-packages"} for part in rel.parts):
            continue
        out.append(path)
    return sorted(out)


def main() -> int:
    failures: list[str] = []
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        if "from aggregate_fake_redis import FakeRedis" in text:
            failures.append(f"{rel}: use relative import for aggregate_fake_redis")

    if failures:
        print("Import style consistency check failed:")
        for item in failures:
            print(f" - {item}")
        return 1
    print("Import style consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
