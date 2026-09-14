"""Gate: consortium threat-matrix worker removed (#5/#9 consortium_prune).

The worker consumed the labels event subject and wrote
``anumana:consortium:threat:*`` Redis keys + the
``orchestrator_consortium_threat_counters`` CH table — all write-only
(zero readers), zero deployment surfaces. The subject transport is now
also removed (no consumer ever replaced the worker).
"""

from __future__ import annotations

import importlib
from pathlib import Path

_ORCHESTRATOR = Path(__file__).resolve().parent.parent.parent / "orchestrator"


def test_consortium_worker_and_matrix_removed() -> None:
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("orchestrator.workers.consortium_counter_worker")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("orchestrator_analytics.consortium_threat_matrix")


def test_labels_jetstream_module_removed() -> None:
    """The subject transport is gone with its last consumer; retro-tag work remains."""
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("messaging.labels_jetstream")
