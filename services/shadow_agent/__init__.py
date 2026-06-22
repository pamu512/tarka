"""Shadow agent: LLM-backed decision providers."""

from __future__ import annotations

import importlib.util
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
        spec = importlib.util.spec_from_file_location(full, flat_py)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {full} from {flat_py}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        return mod
    pkg_dir = _PKG_ROOT / name
    init_py = pkg_dir / "__init__.py"
    if pkg_dir.is_dir() and init_py.is_file():
        spec = importlib.util.spec_from_file_location(
            full,
            init_py,
            submodule_search_locations=[str(pkg_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load package {full} from {pkg_dir}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> ModuleType:
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return _load_submodule(name)
