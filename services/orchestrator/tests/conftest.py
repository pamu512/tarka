"""Pytest path setup for flat orchestrator layout (v1.3.0)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SERVICES = _ROOT.parent
_REPO_ROOT = _SERVICES.parent
for _p in (
    _SERVICES / "ingestor" / "src",
    _SERVICES / "ingestor",
    _SERVICES / "shared",
    _REPO_ROOT / "packages" / "shared-core",
):
    _s = str(_p.resolve())
    if _s not in sys.path:
        sys.path.append(_s)
# Orchestrator must precede sibling services (e.g. shadow_agent/schemas.py is a module).
_root_s = str(_ROOT.resolve())
if _root_s in sys.path:
    sys.path.remove(_root_s)
sys.path.insert(0, _root_s)
# Repo-root ``schemas/`` (UnifiedSignalSchema) collides with orchestrator and shadow_agent.
_repo_s = str(_REPO_ROOT.resolve())
while _repo_s in sys.path:
    sys.path.remove(_repo_s)
for _mod in list(sys.modules):
    if _mod == "schemas" or _mod.startswith("schemas."):
        _file = getattr(sys.modules[_mod], "__file__", "") or ""
        if "orchestrator/schemas" not in _file.replace("\\", "/"):
            del sys.modules[_mod]


@pytest.fixture(autouse=True)
def _default_python_rule_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests historically omit DECISION_API_URL; pin Python backend unless a test overrides."""
    monkeypatch.setenv("RULE_EVAL_BACKEND", "python")
