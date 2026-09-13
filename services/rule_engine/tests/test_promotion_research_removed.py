"""Guard: promotion_research shim removed (orphan after #8).

Its sole caller was ``promotion_feedback.py`` (removed with the dormant NATS
lane). The promotion gate lives in decision-api (``shadow_auto_promote.py``,
``leftover_promote_gate.py``); this shim only bridged rule_engine to the
research simulator for the dead feedback lane.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_RULE_ENGINE = Path(__file__).resolve().parents[1]


def test_promotion_research_module_gone() -> None:
    assert not (_RULE_ENGINE / "promotion_research.py").exists()


def test_no_dangling_references() -> None:
    for py in _RULE_ENGINE.rglob("*.py"):
        if ".venv" in py.parts or "__pycache__" in py.parts:
            continue
        if py == Path(__file__).resolve():
            continue
        assert "promotion_research" not in py.read_text(encoding="utf-8"), py


def test_import_raises() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("promotion_research")
