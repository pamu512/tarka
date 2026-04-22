from __future__ import annotations

"""Single source of truth for ML 9-feature order: delegates to ``ml_scoring.heuristic``."""


import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_feature_order() -> list[str]:
    """Return ``FEATURE_ORDER`` from ``ml_scoring.heuristic`` (same vector as ONNX training)."""
    root = repo_root()
    src = root / "services" / "ml-scoring" / "src"
    p = str(src)
    if p not in sys.path:
        sys.path.insert(0, p)
    from ml_scoring.heuristic import FEATURE_ORDER  # noqa: PLC0415

    return list(FEATURE_ORDER)
