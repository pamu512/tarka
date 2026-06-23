"""Shadow-agent schema types (avoids bare ``schemas`` collisions in monorepo tests)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PKG = Path(__file__).resolve().parent


def _load_schemas_module() -> ModuleType:
    try:
        import schemas as mod  # noqa: PLC0415

        if getattr(mod, "ShadowDecision", None) is not None:
            sys.modules.setdefault("shadow_agent.schemas", mod)
            return mod
    except ImportError:
        pass
    try:
        from shadow_agent import schemas as mod

        return mod
    except ImportError:
        pass
    mod_name = "shadow_agent.schemas"
    cached = sys.modules.get(mod_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(mod_name, _PKG / "schemas.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load shadow_agent schemas module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    sys.modules.setdefault("schemas", mod)
    return mod


_schemas = _load_schemas_module()
HypothesisReport = _schemas.HypothesisReport
SARReportSchema = _schemas.SARReportSchema
ShadowAnalyzeEnvelope = _schemas.ShadowAnalyzeEnvelope
ShadowDecision = _schemas.ShadowDecision

__all__ = [
    "HypothesisReport",
    "SARReportSchema",
    "ShadowAnalyzeEnvelope",
    "ShadowDecision",
]
