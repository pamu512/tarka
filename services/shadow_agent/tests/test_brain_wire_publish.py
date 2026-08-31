"""Scout publisher leftover-helpfulness GET before POST."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scout_pack_publisher import (  # noqa: E402
    build_scout_pack,
    leftover_gate_payload,
    publish_scout_pack,
    scout_report_to_shadow_pack,
)


def _sample_report(*, tenant_id: str | None = "t1") -> dict[str, Any]:
    report: dict[str, Any] = {
        "report_id": "rpt-001",
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
    if tenant_id is not None:
        report["tenant_id"] = tenant_id
    return report


def _gate(
    *,
    helpfulness_blockers: list[str] | None = None,
    leftover_blockers: list[str] | None = None,
    underpowered: bool = False,
    labeled: int = 0,
    tp: int = 0,
    fp: int = 0,
    fp_cap: float = 0.4,
    live_rule_slip: dict[str, Any] | None = None,
) -> dict[str, Any]:
    helpfulness = {
        "blockers": list(helpfulness_blockers or []),
        "underpowered": underpowered,
        "labeled_extras": labeled,
        "extra_tp": tp,
        "extra_fp": fp,
        "fp_rate_cap": fp_cap,
    }
    leftover_blockers = list(
        leftover_blockers if leftover_blockers is not None else helpfulness["blockers"]
    )
    return {
        "leftover_promote_gate": {
            "blockers": leftover_blockers,
            "helpfulness": helpfulness,
        },
        "rule_precision_after_labels": {"rules": []},
        "live_rule_slip": live_rule_slip if live_rule_slip is not None else {"ping": True},
    }


def _two_rule_pack() -> dict[str, Any]:
    return {
        "version": 1,
        "name": "Scout: canvas_hash abc123",
        "mode": "shadow",
        "rules": [
            {
                "id": "r1",
                "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                "score_delta": 25.0,
            },
            {
                "id": "r2",
                "when": [{"op": "eq", "field": "ip_address", "value": "1.2.3.4"}],
                "score_delta": 20.0,
            },
        ],
        "tag_rules": [],
        "authored_by": "scout_coordinated_burst",
        "is_ai_authored": True,
        "scout_report_id": "rpt-001",
    }


def test_fp_over_cap_no_post():
    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(
                return_value=_gate(helpfulness_blockers=["leftover_extras_fp_over_cap"])
            ),
        ),
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_pack(_sample_report()))

    mock_post.assert_not_called()
    assert result["published"] is False
    assert result["reason"] == "leftover_extras_fp_over_cap"


def test_rule_fp_strips_r1_posts_only_r2():
    posted: list[dict] = []

    def fake_post(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(json.loads(json.dumps(pack)))
        return {"status": "created"}

    async def fake_build(report, *, llm_client=None, authored_by=None):
        return _two_rule_pack()

    gate = _gate()
    gate["rule_precision_after_labels"] = {
        "rules": [
            {"rule_id": "r1", "enough_support": True, "fp_rate": 0.8},
            {"rule_id": "r2", "enough_support": False, "fp_rate": 0.9},
        ]
    }
    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(return_value=gate),
        ),
        mock.patch("scout_pack_publisher.build_scout_pack", side_effect=fake_build),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post),
    ):
        result = asyncio.run(publish_scout_pack(_sample_report()))

    assert result["published"] is True
    assert len(posted) == 1
    assert [r["id"] for r in posted[0]["rules"]] == ["r2"]


def test_underpowered_posts_with_evidence_stamp():
    posted: list[dict] = []

    def fake_post(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    gate = _gate(underpowered=True, labeled=3, tp=1, fp=2)
    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(return_value=gate),
        ),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post),
    ):
        result = asyncio.run(publish_scout_pack(_sample_report()))

    assert result["published"] is True
    assert len(posted) == 1
    ev = posted[0]["evidence"]["leftover_helpfulness"]
    assert ev["hint"] == "helpfulness_underpowered"
    assert ev["labeled_extras"] == 3
    assert ev["extra_tp"] == 1
    assert ev["extra_fp"] == 2


def test_missing_tenant_no_get_no_post():
    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(),
        ) as mock_get,
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_pack(_sample_report(tenant_id=None)))

    mock_get.assert_not_called()
    mock_post.assert_not_called()
    assert result["published"] is False
    assert result["reason"] == "leftover_helpfulness_no_tenant"


def test_get_500_leftover_helpfulness_unavailable():
    def boom(req, timeout=10):
        raise urllib.error.HTTPError(
            req.full_url,
            500,
            "Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b"nope"),
        )

    with (
        mock.patch("urllib.request.urlopen", side_effect=boom),
        mock.patch("scout_pack_publisher._post_pack") as mock_post,
    ):
        result = asyncio.run(publish_scout_pack(_sample_report()))

    mock_post.assert_not_called()
    assert result["published"] is False
    assert result["reason"] == "leftover_helpfulness_unavailable"


def test_sla_blocker_only_allows_post():
    posted: list[dict] = []

    def fake_post(pack, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(pack)
        return {"status": "created"}

    gate = _gate(
        leftover_blockers=["leftover_sla_breached"],
        underpowered=True,
        labeled=0,
        live_rule_slip={"rule_id": "r1", "ping": True},
    )
    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(return_value=gate),
        ),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post),
    ):
        result = asyncio.run(publish_scout_pack(_sample_report()))

    assert result["published"] is True
    assert len(posted) == 1


def test_pack_and_post_body_carry_tenant_and_fingerprint_evidence():
    report = _sample_report()
    pack = scout_report_to_shadow_pack(report)
    assert pack["tenant_id"] == "t1"
    assert pack["evidence"]["fingerprint_kind"] == "canvas_hash"
    assert pack["evidence"]["fingerprint_value"] == "abc123"

    posted: list[dict] = []

    def fake_post(body, *, decision_api_url=None, actor="scout_coordinated_burst"):
        posted.append(body)
        return {"status": "created"}

    with (
        mock.patch(
            "scout_pack_publisher.leftover_gate_payload",
            new=mock.AsyncMock(return_value=_gate(underpowered=True, labeled=3, tp=1, fp=2)),
        ),
        mock.patch("scout_pack_publisher._post_pack", side_effect=fake_post),
    ):
        result = asyncio.run(publish_scout_pack(report))

    assert result["published"] is True
    assert len(posted) == 1
    assert posted[0]["tenant_id"] == "t1"
    assert posted[0]["evidence"]["fingerprint_kind"] == "canvas_hash"
    assert posted[0]["evidence"]["fingerprint_value"] == "abc123"
    assert posted[0]["evidence"]["leftover_helpfulness"]["hint"] == "helpfulness_underpowered"


@pytest.mark.asyncio
async def test_leftover_gate_payload_get_headers():
    captured: dict[str, Any] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["gov"] = req.get_header("X-rule-governance-secret")
        captured["actor"] = req.get_header("X-actor")
        return _Resp()

    with (
        mock.patch.dict("os.environ", {"RULE_GOVERNANCE_SECRET": "sekrit"}, clear=False),
        mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        body = await leftover_gate_payload("acme", decision_api_url="http://dec:8001")

    assert body == {"ok": True}
    assert captured["url"] == "http://dec:8001/v1/calibration/shadow-promote-gate?tenant_id=acme"
    assert captured["method"] == "GET"
    assert captured["gov"] == "sekrit"
    assert captured["actor"] == "scout_coordinated_burst"


@pytest.mark.asyncio
async def test_leftover_gate_payload_sends_api_keys_as_x_api_key():
    captured: dict[str, Any] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout=10):
        captured["api_key"] = req.get_header("X-api-key")
        captured["internal"] = req.get_header("X-internal-token")
        return _Resp()

    with (
        mock.patch.dict(
            "os.environ",
            {"API_KEYS": "desk-key,other-key", "CASE_INTERNAL_TOKEN": "tok"},
            clear=False,
        ),
        mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        body = await leftover_gate_payload("acme", decision_api_url="http://dec:8001")

    assert body == {"ok": True}
    assert captured["api_key"] == "desk-key"
    assert captured["internal"] == "tok"


@pytest.mark.asyncio
async def test_llm_build_stamps_fingerprint_evidence():
    report = _sample_report()
    llm_pack = {
        "name": "LLM burst pack",
        "version": 1,
        "mode": "shadow",
        "is_ai_authored": True,
        "authored_by": "vllm",
        "rules": [
            {
                "id": "llm_canvas",
                "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                "score_delta": 20.0,
            }
        ],
    }

    class _Client:
        async def chat_json_validated(self, messages, *, model=None):
            return llm_pack

    pack = await build_scout_pack(report, llm_client=_Client(), authored_by="vllm")
    assert pack is not None
    assert pack["evidence"]["fingerprint_kind"] == "canvas_hash"
    assert pack["evidence"]["fingerprint_value"] == "abc123"
    assert pack["tenant_id"] == "t1"
