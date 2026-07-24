"""Locate repo-root ``adapters/`` (monorepo or core-api image)."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_adapters_on_path() -> Path | None:
    """
    Monorepo: walk up from this file until ``adapters/biometrics`` exists.
    core-api image: ``/app/adapters`` (see services/core-api/Dockerfile).
    Returns the path that should be on ``sys.path`` (parent of ``adapters``), or None.
    """
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "adapters" / "biometrics").is_dir():
            root = str(parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            return parent
    app_root = Path("/app")
    if (app_root / "adapters" / "biometrics").is_dir():
        s = str(app_root)
        if s not in sys.path:
            sys.path.insert(0, s)
        return app_root
    return None
