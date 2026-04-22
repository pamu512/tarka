from __future__ import annotations

"""Pytest hooks for ml-scoring: env before ``main`` is imported (coverage + fast /v1/score)."""


import os

# Fast heuristic-off path for HTTP smoke tests; ONNX/LGBM not needed in unit CI.
os.environ.setdefault("DISABLE_ML", "1")
