"""Tests for the LLM-integrated pack authoring publish path.

Covers:
- LLM unset → deterministic template pack validates and can publish.
- LLM returns invalid / live mode → pack not published.
- LLM returns valid shadow pack → published, authored_by from backend.
- Insufficient evidence → LLM declines, no pack.
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

from pack_author_llm import author_pack_from_hypothesis  # noqa: E402
from scout_pack_publisher import (  # noqa: E402
    build_scout_pack,
    _llm_backend_configured,
    _resolve_authored_by,
)


def _sample_report() -> dict[str, Any]:
    return {
        "report_id": "rpt-test-001",
        "strategy": "coordinated_burst",
        "fingerprint_kind": "canvas_hash",
        "fingerprint_value": "abc123",
        "distinct_account_count": 8,
        "suggested_rule": {
            "id": "scout_canvas_hash_abc123",
            "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
            "score_delta": 25.0,
            "metadata": {
                "is_shadow": True,
                "source": "scout_coordinated_burst",
                "fingerprint_kind": "canvas_hash",
            },
        },
    }


def _valid_llm_pack(authored_by: str = "vllm") -> dict[str, Any]:
    return {
        "name": "LLM burst pack",
        "version": 1,
        "mode": "shadow",
        "is_ai_authored": True,
        "authored_by": authored_by,
        "rules": [
            {
                "id": "llm_canvas_hash_abc123",
                "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                "score_delta": 20.0,
            }
        ],
    }


class _FakeLLMClient:
    """Minimal stub matching chat_json_validated interface."""

    def __init__(self, response: Any):
        self._response = response

    async def chat_json_validated(self, messages: list, *, model: str | None = None) -> Any:
        return self._response

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# LLM unset → deterministic template pack validates and can publish
# ---------------------------------------------------------------------------


def test_no_llm_template_pack_validates():
    """Without an LLM client, build_scout_pack uses the deterministic template."""
    pack = asyncio.run(build_scout_pack(_sample_report(), llm_client=None))
    assert pack is not None
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is True
    assert pack["authored_by"] == "scout_coordinated_burst"
    assert len(pack["rules"]) == 1
    assert pack["rules"][0]["when"][0]["value"] == "abc123"


# ---------------------------------------------------------------------------
# LLM returns valid shadow pack → published, authored_by from backend
# ---------------------------------------------------------------------------


def test_llm_valid_pack_accepted():
    client = _FakeLLMClient(_valid_llm_pack("vllm"))
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is not None
    assert pack["mode"] == "shadow"
    assert pack["authored_by"] == "vllm"
    assert pack["is_ai_authored"] is True


def test_llm_authored_by_propagated():
    client = _FakeLLMClient(_valid_llm_pack("self_hosted"))
    pack = asyncio.run(
        build_scout_pack(
            _sample_report(), llm_client=client, authored_by="self_hosted",
        )
    )
    assert pack is not None
    assert pack["authored_by"] == "self_hosted"


# ---------------------------------------------------------------------------
# LLM returns invalid / live mode → not published
# ---------------------------------------------------------------------------


def test_llm_live_mode_rejected():
    bad = _valid_llm_pack()
    bad["mode"] = "active"
    client = _FakeLLMClient(bad)
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


def test_llm_invalid_schema_rejected():
    client = _FakeLLMClient({"garbage": True})
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


def test_llm_score_delta_over_cap_rejected():
    bad = _valid_llm_pack()
    bad["rules"][0]["score_delta"] = 100
    client = _FakeLLMClient(bad)
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


def test_llm_unknown_field_rejected():
    bad = _valid_llm_pack()
    bad["rules"][0]["when"] = [{"op": "eq", "field": "evil_field", "value": "x"}]
    client = _FakeLLMClient(bad)
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


# ---------------------------------------------------------------------------
# Insufficient evidence → LLM declines → no pack
# ---------------------------------------------------------------------------


def test_llm_insufficient_evidence_no_pack():
    client = _FakeLLMClient({"ok": False, "reason": "insufficient_evidence"})
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


def test_author_pack_from_hypothesis_returns_declined():
    client = _FakeLLMClient({"ok": False, "reason": "insufficient_evidence"})
    result = asyncio.run(
        author_pack_from_hypothesis(_sample_report(), client, authored_by="vllm")
    )
    assert result["ok"] is False
    assert any("llm_declined" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# LLM call failure → no pack (not a crash)
# ---------------------------------------------------------------------------


class _FailingLLMClient:
    async def chat_json_validated(self, messages: list, *, model: str | None = None) -> Any:
        raise ConnectionError("network down")

    async def aclose(self) -> None:
        pass


def test_llm_call_failure_returns_none():
    client = _FailingLLMClient()
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is None


# ---------------------------------------------------------------------------
# Backend detection helpers
# ---------------------------------------------------------------------------


def test_llm_backend_configured_when_set():
    with mock.patch.dict("os.environ", {"SHADOW_LLM_BACKEND": "vllm"}):
        assert _llm_backend_configured() is True


def test_llm_backend_not_configured_when_empty():
    with mock.patch.dict("os.environ", {}, clear=True):
        assert _llm_backend_configured() is False


def test_llm_backend_not_configured_for_ollama():
    with mock.patch.dict("os.environ", {"SHADOW_LLM_BACKEND": "ollama"}):
        assert _llm_backend_configured() is False


def test_resolve_authored_by_vllm():
    with mock.patch.dict("os.environ", {"SHADOW_LLM_BACKEND": "vllm"}):
        assert _resolve_authored_by() == "vllm"


def test_resolve_authored_by_self_hosted():
    with mock.patch.dict("os.environ", {"SHADOW_LLM_BACKEND": "self-hosted"}):
        assert _resolve_authored_by() == "self_hosted"


def test_resolve_authored_by_default():
    with mock.patch.dict("os.environ", {}, clear=True):
        assert _resolve_authored_by() == "scout"


# ---------------------------------------------------------------------------
# Provenance fields on LLM-authored pack
# ---------------------------------------------------------------------------


def test_llm_pack_has_scout_report_id():
    client = _FakeLLMClient(_valid_llm_pack("vllm"))
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is not None
    assert pack["scout_report_id"] == "rpt-test-001"


def test_llm_pack_has_created_at():
    client = _FakeLLMClient(_valid_llm_pack("vllm"))
    pack = asyncio.run(
        build_scout_pack(_sample_report(), llm_client=client, authored_by="vllm")
    )
    assert pack is not None
    assert "created_at" in pack
