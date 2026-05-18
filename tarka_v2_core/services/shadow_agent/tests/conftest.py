"""Ensure ``shadow_agent`` and ``ingestor`` package roots are importable for tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SHADOW_AGENT_DIR = Path(__file__).resolve().parents[1]
_SHADOW_SRC = _SHADOW_AGENT_DIR / "src"
_INGESTOR_SRC = _SHADOW_AGENT_DIR.parent / "ingestor" / "src"
_SHARED_SRC = _SHADOW_AGENT_DIR.parent / "shared"

for _p in (_SHADOW_SRC, _INGESTOR_SRC, _SHARED_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
