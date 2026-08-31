"""Tests for the end-to-end scout burst → pack publish loop.

Covers:
- probe with LLM unset → one validated template pack publish attempted
- probe with LLM valid pack → that pack is what gets POSTed; authored_by from backend
- probe with LLM invalid/live/decline → no POST
- second probe same fingerprint → no second pack (dedup)
- evaluate inject path does not publish
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_sentinel = type(sys)("shadow_schemas")
_sentinel.HypothesisReport = type("HypothesisReport", (), {"model_dump": lambda s, **kw: {}})
sys.modules.setdefault("shadow_schemas", _sentinel)

from scout_pack_publisher import (  # noqa: E402
    _published_fingerprints,
    build_scout_pack,
    publish_scout_burst_packs,
)


def _sample_scan_payload(*, count: int = 1) -> dict[str, Any]:
    reports = []
    for i in range(count):
        reports.append(
            {
                "report_id": f"rpt-{i:03d}",
                "strategy": "coordinated_burst",
                "fingerprint_kind": "canvas_hash",
                "fingerprint_value": f"fp_value_{i}",
                "distinct_account_count": 8,
                "suggested_rule": {
                    "id": f"scout_canvas_hash_fp_value_{i}",
                    "when": [{"op": "eq", "field": "canvas_hash", "value": f"fp_value_{i}"}],
                    "score_delta": 25.0,
                    "metadata": {
                        "is_shadow": True,
                        "source": "scout_coordinated_burst",
                        "fingerprint_kind": "canvas_hash",
                    },
                },
            }
        )
    return {
        "strategy": "coordinated_burst",
        "tenant_id": "t1",
        "bursts_found": count,
        "hypothesis_reports": reports,
        "hypothesis_reports_blocked": [],
    }


class _FakeLLMClient:
    def __init__(self, response: Any):
        self._response = response
        self.call_count = 0

    async def chat_json_validated(self, messages: list, *, model: str | None = None) -> Any:
        self.call_count += 1
        return self._response

    async def aclose(self) -> None:
        pass


def _valid_llm_pack(authored_by: str = "vllm", value: str = "fp_value_0") -> dict[str, Any]:
    return {
        "name": "LLM burst pack",
        "version": 1,
        "mode": "shadow",
        "is_ai_authored": True,
        "authored_by": authored_by,
        "rules": [
            {
                "id": f"llm_canvas_hash_{value}",
                "when": [{"op": "eq", "field": "canvas_hash", "value": value}],
                "score_delta": 20.0,
            }
        ],
    }


@pytest.fixture(autouse=True)
def _clear_dedup():
    """Reset dedup set between tests."""
    _published_fingerprints.clear()
    yield
    _published_fingerprints.clear()


@pytest.fixture(autouse=True)
def _allow_leftover_gate():
    """Existing burst tests are not leftover-critic cases — allow publish."""
    gate = {
        "leftover_promote_gate": {
            "helpfulness": {
                "blockers": [],
                "underpowered": True,
                "labeled_extras": 0,
                "extra_tp": 0,
                "extra_fp": 0,
                "fp_rate_cap": 0.4,
            }
        },
        "rule_precision_after_labels": {"rules": []},
    }
    with mock.patch(
        "scout_pack_publisher.leftover_gate_payload",
        new=mock.AsyncMock(return_value=gate),
    ):
        yield


# ---------------------------------------------------------------------------
# probe with LLM unset → template pack publish attempted
# ---------------------------------------------------------------------------


def test_probe_no_llm_publishes_template_pack():
    """Without LLM, publish_scout_burst_packs POSTs the deterministic template."""
    posted: list[dict] = []

    def fake_post_pack(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post_pack),
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    assert len(result["published"]) == 1
    assert len(result["dropped"]) == 0
    assert len(posted) == 1
    assert posted[0]["mode"] == "shadow"
    assert posted[0]["is_ai_authored"] is True
    assert posted[0]["authored_by"] == "scout_coordinated_burst"


# ---------------------------------------------------------------------------
# probe with LLM valid pack → that pack is what gets POSTed
# ---------------------------------------------------------------------------


def test_probe_llm_valid_pack_posted():
    posted: list[dict] = []

    def fake_post_pack(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    llm_pack = _valid_llm_pack("vllm")
    client = _FakeLLMClient(llm_pack)

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict(
            "os.environ",
            {"SHADOW_LLM_BACKEND": "vllm", "SHADOW_LLM_BASE_URL": "http://vllm:8000/v1"},
        ),
        mock.patch("llm_client.build_shadow_llm_client", return_value=client),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post_pack),
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    assert len(result["published"]) == 1
    assert len(posted) == 1
    assert posted[0]["authored_by"] == "vllm"
    assert posted[0]["mode"] == "shadow"
    assert posted[0]["name"] == "LLM burst pack"


def test_probe_llm_authored_by_from_backend():
    posted: list[dict] = []

    def fake_post_pack(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    client = _FakeLLMClient(_valid_llm_pack("self_hosted"))

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict(
            "os.environ",
            {"SHADOW_LLM_BACKEND": "self-hosted", "SHADOW_LLM_BASE_URL": "http://my-llm:8000/v1"},
        ),
        mock.patch("llm_client.build_shadow_llm_client", return_value=client),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post_pack),
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    assert len(result["published"]) == 1
    assert posted[0]["authored_by"] == "self_hosted"


# ---------------------------------------------------------------------------
# probe with LLM invalid / live / decline → no POST
# ---------------------------------------------------------------------------


def test_probe_llm_live_mode_no_post():
    bad = _valid_llm_pack()
    bad["mode"] = "active"
    client = _FakeLLMClient(bad)

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict(
            "os.environ",
            {"SHADOW_LLM_BACKEND": "vllm", "SHADOW_LLM_BASE_URL": "http://vllm:8000/v1"},
        ),
        mock.patch("llm_client.build_shadow_llm_client", return_value=client),
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    mock_post.assert_not_called()
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["reason"] == "pack_rejected_by_validation"


def test_probe_llm_insufficient_evidence_no_post():
    client = _FakeLLMClient({"ok": False, "reason": "insufficient_evidence"})

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict(
            "os.environ",
            {"SHADOW_LLM_BACKEND": "vllm", "SHADOW_LLM_BASE_URL": "http://vllm:8000/v1"},
        ),
        mock.patch("llm_client.build_shadow_llm_client", return_value=client),
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    mock_post.assert_not_called()
    assert len(result["dropped"]) == 1


def test_probe_llm_invalid_schema_no_post():
    client = _FakeLLMClient({"garbage": True})

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict(
            "os.environ",
            {"SHADOW_LLM_BACKEND": "vllm", "SHADOW_LLM_BASE_URL": "http://vllm:8000/v1"},
        ),
        mock.patch("llm_client.build_shadow_llm_client", return_value=client),
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    mock_post.assert_not_called()
    assert len(result["dropped"]) == 1


# ---------------------------------------------------------------------------
# second probe same fingerprint → no second pack (dedup)
# ---------------------------------------------------------------------------


def test_dedup_same_fingerprint_no_second_pack():
    call_count = 0

    def fake_post_pack(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        nonlocal call_count
        call_count += 1
        return {"status": "created"}

    payload = _sample_scan_payload(count=1)
    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post_pack),
    ):
        r1 = asyncio.run(publish_scout_burst_packs(payload))
        r2 = asyncio.run(publish_scout_burst_packs(payload))

    assert len(r1["published"]) == 1
    assert call_count == 1
    assert len(r2["published"]) == 0
    assert len(r2["skipped"]) == 1
    assert r2["skipped"][0]["reason"] == "already_published"


def test_dedup_different_fingerprint_both_published():
    posted: list[dict] = []

    def fake_post_pack(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    payload = _sample_scan_payload(count=2)
    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post_pack),
    ):
        result = asyncio.run(publish_scout_burst_packs(payload))

    assert len(result["published"]) == 2
    assert len(posted) == 2


# ---------------------------------------------------------------------------
# evaluate inject path does not publish
# ---------------------------------------------------------------------------


def test_evaluate_path_does_not_import_publish():
    """agent.py (evaluate path) must not import publish functions."""
    agent_path = Path(__file__).resolve().parents[1] / "agent.py"
    source = agent_path.read_text(encoding="utf-8")
    assert "publish_scout_pack" not in source
    assert "publish_scout_burst_packs" not in source
    assert "build_scout_pack" not in source


# ---------------------------------------------------------------------------
# empty scan → no-op
# ---------------------------------------------------------------------------


def test_empty_scan_no_publish():
    payload: dict[str, Any] = {
        "strategy": "coordinated_burst",
        "bursts_found": 0,
        "hypothesis_reports": [],
    }
    with mock.patch("scout_pack_publisher._post_pack") as mock_post:
        result = asyncio.run(publish_scout_burst_packs(payload))

    mock_post.assert_not_called()
    assert result["published"] == []
    assert result["dropped"] == []
    assert result["skipped"] == []
