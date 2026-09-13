"""Gate: hypothesis_promotion_graph worker removed (#8 hypothesis_nats_prune).

The worker consumed ``tarka.hypothesis.promoted`` from TARKA_PROMOTIONS;
its only producer (rule_engine promotion_feedback.py) is deleted in the
same change, so the whole loop is dead.
"""

from __future__ import annotations

import importlib


def test_hypothesis_promotion_graph_removed() -> None:
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("orchestrator.workers.hypothesis_promotion_graph")
