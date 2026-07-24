"""Locate ``services/shared`` for auth_rbac imports (repo layout or core-api image)."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_services_shared_on_path() -> Path:
    """
    Monorepo: ``…/services/decision-api/src/decision_api/*.py`` → ``services/shared``.
    core-api image: ``/app/decision_api/*.py`` → ``/app/shared``.
    """
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    if len(here.parents) > 3:
        candidates.append(here.parents[3] / "shared")
    candidates.append(here.parents[1] / "shared")
    shared = next((p for p in candidates if p.is_dir()), candidates[-1])
    s = str(shared)
    if s not in sys.path:
        sys.path.insert(0, s)
    return shared
