from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_adapters_path():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "vendors"
        / "adapters_path.py"
    )
    spec = importlib.util.spec_from_file_location("adapters_path_mod", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ensure_adapters_on_path_finds_monorepo_biometrics() -> None:
    mod = _load_adapters_path()
    root = mod.ensure_adapters_on_path()
    assert root is not None
    assert (root / "adapters" / "biometrics").is_dir()
