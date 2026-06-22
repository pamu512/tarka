"""Pytest path setup for flat orchestrator layout (v1.3.0)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SERVICES = _ROOT.parent
for _p in (
    _SERVICES / "ingestor" / "src",
    _SERVICES / "ingestor",
    _SERVICES / "shared",
    _SERVICES.parent / "packages" / "shared-core",
):
    _s = str(_p.resolve())
    if _s not in sys.path:
        sys.path.append(_s)
# Orchestrator must precede sibling services (e.g. shadow_agent/schemas.py is a module).
_root_s = str(_ROOT.resolve())
if _root_s in sys.path:
    sys.path.remove(_root_s)
sys.path.insert(0, _root_s)
for _mod in list(sys.modules):
    if _mod == "schemas" or _mod.startswith("schemas."):
        _file = getattr(sys.modules[_mod], "__file__", "") or ""
        if "orchestrator/schemas" not in _file.replace("\\", "/"):
            del sys.modules[_mod]
