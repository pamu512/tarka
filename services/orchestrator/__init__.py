"""Tarka ingestion orchestrator (gateway)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

_PKG_ROOT = Path(__file__).resolve().parent


def _alias_module(full_name: str, mod: ModuleType) -> ModuleType:
    sys.modules[full_name] = mod
    return mod


def _load_submodule(name: str) -> ModuleType:
    full = f"{__name__}.{name}"
    existing = sys.modules.get(full)
    if existing is not None:
        return existing
    flat_py = _PKG_ROOT / f"{name}.py"
    if flat_py.is_file():
        mod = importlib.import_module(name)
        return _alias_module(full, mod)
    if (_PKG_ROOT / name).is_dir():
        mod = importlib.import_module(name)
        _alias_module(full, mod)
        prefix = f"{name}."
        for loaded_name, loaded_mod in list(sys.modules.items()):
            if loaded_name.startswith(prefix):
                _alias_module(f"{__name__}.{loaded_name}", loaded_mod)
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> ModuleType:
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return _load_submodule(name)
