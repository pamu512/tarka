#!/usr/bin/env python3
"""
Prompt path ``services/signal-api/heartbeat.py``: adds ``src`` + repo root to ``sys.path``.

Import the FastAPI router from :mod:`signal_api.heartbeat` or run the Redis monitor::

    python heartbeat.py   # same as ``monitor_main()`` from ``signal_api.heartbeat``
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
_repo = Path(__file__).resolve().parents[3]
_src = _root / "src"
for p in (_src, _repo):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from signal_api.heartbeat import monitor_main, router as heartbeat_router  # noqa: E402

__all__ = ["heartbeat_router", "monitor_main"]

if __name__ == "__main__":
    monitor_main()
