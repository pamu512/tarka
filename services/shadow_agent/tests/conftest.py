"""Pytest path setup for flat shadow_agent layout (v1.3.0)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SERVICES = _ROOT.parent
for _p in (
    _ROOT,
    _SERVICES / "ingestor" / "src",
    _SERVICES / "ingestor",
    _SERVICES.parent / "packages" / "shared-core",
    _SERVICES,
):
    _s = str(_p.resolve())
    if _s not in sys.path:
        sys.path.insert(0, _s)
