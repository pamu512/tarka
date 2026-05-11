#!/usr/bin/env python3
"""
Entrypoint for prompt path ``services/signal-api/workers/duck_mirror.py``.

Adds ``src`` and repo root to ``sys.path``, then runs :func:`signal_api.workers.duck_mirror.main`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_signal_api_root = Path(__file__).resolve().parents[1]
_repo_root = Path(__file__).resolve().parents[4]
_src = _signal_api_root / "src"
for p in (_src, _repo_root):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from signal_api.workers.duck_mirror import main  # noqa: E402

if __name__ == "__main__":
    main()
