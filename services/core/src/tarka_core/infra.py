"""Environment-driven selection of Tarka Micro vs full external dependencies."""

from __future__ import annotations

import os


def is_tarka_micro_environ() -> bool:
    """Return True when ``TARKA_ENV`` selects the in-process / no-NATS profile."""
    v = (os.environ.get("TARKA_ENV") or "").strip().lower()
    return v in ("micro", "tarka_micro", "local_micro")
