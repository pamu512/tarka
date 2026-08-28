"""Evaluate hop contract v1.2 — role, named edges, empty graph URL."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from decision_api.evaluate import enrichment
from decision_api.inference_build import build_inference_context
from decision_api.schemas import EvaluatePartyIn, EvaluateRequest

import graph_contract as gc


@pytest.fixture(autouse=True)
def _clean_registry():
    gc.reset_tenant_registry()
    yield
    gc.reset_tenant_registry()


def _bind():
    enrichment.bind_runtime(
        circuit_graph=object(),
        circuit_feature=object(),
        metrics_inc=lambda *_a, **_k: None,
        upstream_headers=lambda: {},
    )


def test_evaluate_request_requires_role():
    with pytest.raises(ValidationError):
        EvaluateRequest(
            tenant_id="t1", event_type="login", entity_id="u1", payload={}
        )
    r = EvaluateRequest(
        tenant_id="t1",
        event_type="login",
        entity_id="u1",
        role="member",
        payload={},
    )
    assert r.role == "member"
    assert r.entity_id == "u1"


def test_evaluate_parties_accept_entity_id_or_user_id():
    p = EvaluatePartyIn(user_id="u2", role="member")
    assert p.resolved_user_id() == "u2"
    p2 = EvaluatePartyIn(entity_id="u3", role="member")
    assert p2.resolved_user_id() == "u3"
    with pytest.raises(ValidationError):
        EvaluatePartyIn(role="member")


def test_unsigned_role_raises_when_registry_locked():
    gc.register_roles("t1", ["member"])
    from decision_api.graph_hop_contract import validate_evaluate_roles

    validate_evaluate_roles("t1", "member", parties=None)
    with pytest.raises(gc.UnsignedGraphToken):
        validate_evaluate_roles("t1", "ghost", parties=None)
    with pytest.raises(gc.UnsignedGraphToken):
        validate_evaluate_roles(
            "t1",
            "member",
            parties=[{"entity_id": "u2", "role": "spectre"}],
        )


def test_inference_includes_named_edges_from_graph_meta():
    ctx = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=20.0,
        features={},
        graph_meta={
            "risk_score": 40.0,
            "risk_factors": ["shared_devices:1"],
            "named_edges": [{"from_id": "u1", "to_id": "d1", "type": "USED"}],
            "multi_id_user_ids": ["u2"],
            "roles": ["member", "cashier"],
        },
    )
    assert ctx["named_edges"][0]["type"] == "USED"
    assert ctx["multi_id_user_ids"] == ["u2"]
    assert ctx["roles"] == ["member", "cashier"]


@pytest.mark.asyncio
async def test_empty_graph_url_skips_cleanly_graph_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind()
    monkeypatch.setattr(enrichment.settings, "graph_service_url", "")
    tags: list[str] = []
    data = await enrichment.fetch_graph_risk_wrapped(
        http=object(),  # type: ignore[arg-type]
        tenant_id="t1",
        entity_id="e1",
        degrade_tags=tags,
        tenant_flags={},
    )
    assert data is None
    assert "graph:unconfigured" in tags
    assert "graph:missing" in tags
    assert "graph:unavailable" not in tags
    # Do not stub neighbors when the hop is off.
    assert data is None


@pytest.mark.asyncio
async def test_evaluate_consumes_named_edges_when_graph_url_set(monkeypatch):
    """GRAPH_SERVICE_URL set → multi-id + named edges reach inference and pack-why."""
    from unittest.mock import patch

    import httpx
    from decision_api.main import get_session

    graph_blob = {
        "entity_id": "alice",
        "risk_score": 18.0,
        "risk_factors": ["shared_devices:1"],
        "named_edges": [
            {"from_id": "alice", "to_id": "dev-1", "type": "USED"},
            {"from_id": "bob", "to_id": "dev-1", "type": "USED"},
        ],
        "multi_id_user_ids": ["bob"],
        "roles": ["member"],
        "scored": True,
    }

    monkeypatch.setattr(enrichment.settings, "graph_service_url", "http://graph.test")
    monkeypatch.setenv("GRAPH_SERVICE_URL", "http://graph.test")
    from decision_api.config import settings as _cfg

    monkeypatch.setattr(_cfg, "graph_service_url", "http://graph.test")

    mock_session = AsyncMock()
    captured: list[object] = []

    def _add(obj):
        captured.append(obj)

    mock_session.add = MagicMock(side_effect=_add)
    mock_session.commit = AsyncMock()

    async def _override():
        yield mock_session

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=[])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            with patch("decision_api.main.load_rules"):
                with patch(
                    "decision_api.main.evaluate_json_rules",
                    return_value=([], [], 0.0, []),
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
                                return_value=graph_blob,
                            ):
                                from decision_api.main import app

                                app.state.http = AsyncMock()
                                app.dependency_overrides[get_session] = _override
                                try:
                                    transport = httpx.ASGITransport(app=app)
                                    async with httpx.AsyncClient(
                                        transport=transport, base_url="http://test"
                                    ) as client:
                                        client.headers.update({"x-api-key": "test-key"})
                                        r = await client.post(
                                            "/v1/decisions/evaluate",
                                            json={
                                                "tenant_id": "t-graph",
                                                "event_type": "payment",
                                                "entity_id": "alice",
                                                "role": "member",
                                                "parties": [
                                                    {"entity_id": "bob", "role": "member"}
                                                ],
                                                "payload": {"amount": 10},
                                            },
                                        )
                                finally:
                                    app.dependency_overrides.pop(get_session, None)

    assert r.status_code == 200, r.text
    data = r.json()
    inf = data["inference_context"]
    assert inf["named_edges"][0]["type"] == "USED"
    assert "bob" in inf["multi_id_user_ids"]
    assert "member" in inf["roles"]
    assert captured, "expected audit row"
    snap = getattr(captured[0], "payload_snapshot", None) or {}
    why = snap.get("pack_why") or {}
    graph_why = why.get("graph") if isinstance(why, dict) else None
    assert graph_why is not None
    assert graph_why["named_edges"][0]["type"] == "USED"
    assert graph_why.get("invented_edges") is False
    assert "bob" in graph_why["multi_id_user_ids"]
