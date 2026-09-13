"""Gate: consortium threat-matrix worker removed (#5/#9 consortium_prune).

The worker consumed ``tarka.events.labels`` and wrote
``anumana:consortium:threat:*`` Redis keys + the
``orchestrator_consortium_threat_counters`` CH table — all write-only
(zero readers), zero deployment surfaces. Labels publishing itself is
unaffected: producers and other consumers (label_propagator,
shadow_retro_tag, label DLQ reader) keep flowing.
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


def test_labels_jetstream_helpers_and_config_removed() -> None:
    src = (_ORCHESTRATOR / "messaging" / "labels_jetstream.py").read_text(encoding="utf-8")
    assert "consortium_labels_durable_name" not in src
    assert "consortium_labels_labels" not in src  # write typo guard
    assert "consortium_labels_fetch_batch_size" not in src

    config_src = (_ORCHESTRATOR / "config.py").read_text(encoding="utf-8")
    assert "consortium_labels_jetstream" not in config_src


def test_labels_publishes_still_flow() -> None:
    """Deleting the worker must not break the labels bus itself."""
    labels_jetstream = assert_labels_module_importable()
    assert hasattr(labels_jetstream, "TARKA_LABELS_SUBJECT")


def assert_labels_module_importable():
    return importlib.import_module("messaging.labels_jetstream")
