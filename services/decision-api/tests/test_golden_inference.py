"""Golden key parity for inference_context v2 (contracts/golden)."""

import json
from pathlib import Path

import pytest
from decision_api.inference_build import build_inference_context

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GOLDEN_PATH = _REPO_ROOT / "contracts" / "golden" / "inference-context-v3.example.json"


@pytest.fixture
def golden_keys() -> set[str]:
    data = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    return set(data.keys())


def test_build_inference_context_includes_all_golden_keys(golden_keys: set[str]):
    ctx = build_inference_context(
        signal_tags=["sdk:vpn", "ingress:replay_payload"],
        rule_hits=["replay_rule"],
        ml_score=55.0,
        final_score=72.0,
        features={
            "event_count_5m": 3,
            "event_count_1h": 10,
            "event_count_24h": 100,
            "distinct_device_id_24h": 2,
        },
    )
    missing = golden_keys - set(ctx.keys())
    assert not missing, f"inference_context missing keys vs golden: {missing}"


def test_golden_file_exists():
    assert _GOLDEN_PATH.is_file(), f"expected {_GOLDEN_PATH}"
