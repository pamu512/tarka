"""Re-export canonical limiter from ``services/shared``."""

from __future__ import annotations

import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    candidate = parent / "shared"
    if candidate.is_dir() and (candidate / "minute_rate_limit.py").is_file():
        sys.path.insert(0, str(candidate))
        break

from minute_rate_limit import MinuteRateLimiter

__all__ = ["MinuteRateLimiter"]
