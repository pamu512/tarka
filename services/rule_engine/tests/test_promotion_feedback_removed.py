"""Gate: promotion-feedback NATS loop removed (#8 hypothesis_nats_prune).

``tarka.hypothesis.deployed`` and ``tarka.hypothesis.promoted`` had zero
readers — the Rust ``tarka-rule-engine-watcher`` named in old docstrings
never existed, and the orchestrator graph consumer is deleted with them.
The Redis half of hypothesis deploy stays (live reader: shadow_hypothesis).
"""

from __future__ import annotations

import importlib
import inspect


def test_promotion_feedback_module_removed() -> None:
    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("promotion_feedback")


def test_hypothesis_deploy_is_redis_only() -> None:
    hypothesis_deploy = importlib.import_module("hypothesis_deploy")
    src = inspect.getsource(hypothesis_deploy)
    assert "import nats" not in src
    assert "nats.connect" not in src
    assert "_nats_url" not in src
    assert hasattr(hypothesis_deploy, "publish_hypothesis_deployed")
