"""Resolve ``services/shared`` on ``sys.path`` for flat and Docker (/app) layouts."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_shared_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "shared"
        if candidate.is_dir() and (candidate / "observability.py").is_file():
            p = str(candidate)
            if p not in sys.path:
                sys.path.insert(0, p)
            return
