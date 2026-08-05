"""Location cohort / co-presence evidence — unit + evaluate contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from decision_api.location_cohort_evidence import (
    SCHEMA_ID,
    build_location_cohort_evidence,
)
from decision_api.partner_fusion import graph_writeback_hints, signals_to_feature_tags
from decision_api.policy_routing import build_canary_cohort_audit

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "oss"
    / "fixtures"
    / "partner_fusion_signals.json"
)


def test_build_location_cohort_evidence_absent_when_no_signals():
    assert (
        build_location_cohort_evidence(
            tags=["sdk:vpn"],
            inference_context={"copresence_risk": 0.0},
            location_meta=None,
            graph_meta=None,
            partner_graph_hints=None,
            canary_cohort=build_canary_cohort_audit("t1", "e1", salt_version="policy_v1"),
        )
        is None
    )


def test_build_location_cohort_evidence_absent_on_degrade_tags_only():
    assert (
        build_location_cohort_evidence(
            tags=["location:unavailable", "graph:unavailable"],
            inference_context={"copresence_risk": 0.0},
            location_meta=None,
            graph_meta=None,
            partner_graph_hints=None,
            canary_cohort=build_canary_cohort_audit("t1", "e1", salt_version="policy_v1"),
        )
        is None
    )


def test_build_location_cohort_evidence_from_location_meta():
    evidence = build_location_cohort_evidence(
        tags=["location:copresence_elevated"],
        inference_context={"copresence_risk": 0.65},
        location_meta={
            "copresence_risk": 0.65,
            "impossible_travel_risk": 0.5,
            "location_confidence": 0.7,
        },
        graph_meta={"seen_at_peer_count_24h": 4},
        partner_graph_hints=None,
        canary_cohort=build_canary_cohort_audit("t1", "e1", salt_version="policy_v1"),
    )
    assert evidence is not None
    assert evidence["schema_id"] == SCHEMA_ID
    assert "cohort" in evidence
    assert evidence["cohort"]["cohort_sticky_id"]
    assert evidence["copresence"]["copresence_risk"] == 0.65
    assert evidence["graph"]["seen_at_peer_count_24h"] == 4
    assert "location:copresence_elevated" in evidence["tags"]


def test_build_location_cohort_evidence_partner_seen_at():
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sigs = [SimpleNamespace(**row) for row in raw["signals"]]
    feats, tags, _ = signals_to_feature_tags(sigs)
    hints = graph_writeback_hints(
        tenant_id="t1",
        entity_id="e1",
        transaction_id="tx1",
        tags=tags,
        features=feats,
    )
    evidence = build_location_cohort_evidence(
        tags=tags,
        inference_context=None,
        location_meta=None,
        graph_meta=None,
        partner_graph_hints=hints,
        canary_cohort=build_canary_cohort_audit("t1", "e1", salt_version="policy_v1"),
    )
    assert evidence is not None
    assert evidence["graph"]["seen_at_edges"]
    assert evidence["graph"]["place_vertices"]
    assert any(t.startswith("vendor:incognia") for t in evidence["tags"])


@pytest.fixture
async def cohort_eval_client():
    """Minimal evaluate client capturing audit snapshot."""
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
    os.environ["API_KEYS"] = ""

    mock_session = AsyncMock()
    captured: list = []

    def _capture_add(obj):
        captured.append(obj)

    mock_session.add = MagicMock(side_effect=_capture_add)
    mock_session.commit = AsyncMock()

    async def _session_override():
        yield mock_session

    location_meta = {
        "copresence_risk": 0.65,
        "impossible_travel_risk": 0.5,
        "geo_consistency_risk": 0.2,
        "location_confidence": 0.7,
        "tags": ["location:copresence_elevated"],
    }
    graph_risk = {"seen_at_peer_count_24h": 4, "risk_score": 55}

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(
                return_value=["location:copresence_elevated"]
            )
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    with patch(
                        "decision_api.main.evaluate_json_rules",
                        return_value=([], ["location:copresence_elevated"], 18.0, []),
                    ):
                        with patch(
                            "decision_api.main.evaluate_opa_or_raise",
                            new_callable=AsyncMock,
                            return_value=None,
                        ):
                            with patch(
                                "decision_api.main._fetch_ml_score_wrapped",
                                new_callable=AsyncMock,
                                return_value=(None, {}),
                            ):
                                with patch(
                                    "decision_api.main._fetch_graph_risk_wrapped",
                                    new_callable=AsyncMock,
                                    return_value=graph_risk,
                                ):
                                    with patch(
                                        "decision_api.main._fetch_location_evaluation_wrapped",
                                        new_callable=AsyncMock,
                                        return_value=location_meta,
                                    ):
                                        from decision_api.config import settings as cfg
                                        from decision_api.main import app, get_session

                                        cfg.location_service_url = "http://location.test"
                                        app.state.http = AsyncMock()
                                        app.dependency_overrides = {}
                                        app.dependency_overrides[get_session] = (
                                            _session_override
                                        )
                                        transport = httpx.ASGITransport(app=app)
                                        async with httpx.AsyncClient(
                                            transport=transport,
                                            base_url="http://testserver",
                                        ) as c:
                                            c._captured = captured
                                            c.tarka_app = app
                                            yield c
                                        app.dependency_overrides.pop(get_session, None)
                                        cfg.location_service_url = ""


@pytest.mark.asyncio
async def test_evaluate_surfaces_cohort_partner_evidence(cohort_eval_client):
    """Evaluate audit must include location_cohort_evidence.cohort when signals present."""
    c = cohort_eval_client
    r = await c.post(
        "/v1/decisions/evaluate",
        json={
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "u-cohort",
            "payload": {"distinct_session_id_24h": 4},
            "metadata": {"cohort_fixture": True},
        },
        headers={},
    )
    assert r.status_code == 200
    assert len(c._captured) == 1
    snap = c._captured[0].payload_snapshot
    evidence = snap.get("location_cohort_evidence")
    assert evidence is not None
    assert "cohort" in evidence
    assert evidence["copresence"]["copresence_risk"] >= 0.5
    assert "location:copresence_elevated" in (evidence.get("tags") or [])


@pytest.fixture
async def degrade_only_eval_client():
    """Evaluate client when location/graph are unavailable — no cohort evidence."""
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
    os.environ["API_KEYS"] = ""

    mock_session = AsyncMock()
    captured: list = []

    def _capture_add(obj):
        captured.append(obj)

    mock_session.add = MagicMock(side_effect=_capture_add)
    mock_session.commit = AsyncMock()

    async def _session_override():
        yield mock_session

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(
                return_value=["location:unavailable", "graph:unavailable"]
            )
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    with patch(
                        "decision_api.main.evaluate_json_rules",
                        return_value=([], ["location:unavailable", "graph:unavailable"], 0.0, []),
                    ):
                        with patch(
                            "decision_api.main.evaluate_opa_or_raise",
                            new_callable=AsyncMock,
                            return_value=None,
                        ):
                            with patch(
                                "decision_api.main._fetch_ml_score_wrapped",
                                new_callable=AsyncMock,
                                return_value=(None, {}),
                            ):
                                with patch(
                                    "decision_api.main._fetch_graph_risk_wrapped",
                                    new_callable=AsyncMock,
                                    return_value=None,
                                ):
                                    with patch(
                                        "decision_api.main._fetch_location_evaluation_wrapped",
                                        new_callable=AsyncMock,
                                        return_value=None,
                                    ):
                                        from decision_api.config import settings as cfg
                                        from decision_api.main import app, get_session

                                        cfg.location_service_url = "http://location.test"
                                        app.state.http = AsyncMock()
                                        app.dependency_overrides = {}
                                        app.dependency_overrides[get_session] = (
                                            _session_override
                                        )
                                        transport = httpx.ASGITransport(app=app)
                                        async with httpx.AsyncClient(
                                            transport=transport,
                                            base_url="http://testserver",
                                        ) as c:
                                            c._captured = captured
                                            c.tarka_app = app
                                            yield c
                                        app.dependency_overrides.pop(get_session, None)
                                        cfg.location_service_url = ""


@pytest.mark.asyncio
async def test_evaluate_omits_cohort_evidence_on_degrade_tags_only(degrade_only_eval_client):
    """Evaluate audit must omit location_cohort_evidence when only degrade tags present."""
    c = degrade_only_eval_client
    r = await c.post(
        "/v1/decisions/evaluate",
        json={
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "u-degrade",
            "payload": {},
            "metadata": {},
        },
        headers={},
    )
    assert r.status_code == 200
    assert len(c._captured) == 1
    snap = c._captured[0].payload_snapshot
    assert "location_cohort_evidence" not in snap
