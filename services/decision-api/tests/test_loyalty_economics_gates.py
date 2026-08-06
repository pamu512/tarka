"""Loyalty economics multi-gate — hygiene, thresholds, non-deny."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from decision_api.loyalty_economics import SCHEMA_ID, evaluate_loyalty_economics


def _cfg(**over):
    base = {
        "schema_id": "tarka.loyalty_program_config/v1",
        "program_id": "default",
        "config_version": "1",
        "effective_at": "2026-01-01T00:00:00Z",
        "acquisition_cost_minor": 2500,
        "retention_cost_minor": 500,
        "target_loyalty_ltv_ratio": 0.12,
        "ineligible_above_ratio": 0.25,
        "restore_at_or_below_ratio": 0.12,
        "min_dwell_seconds": 86400,
        "window": "trailing_90d",
        "velocity_window": "trailing_7d",
        "new_member_grace_days": 0,
        "vip_entity_ids": [],
        "max_feed_age_seconds": 86400,
    }
    base.update(over)
    return base


def _complete_feeds(entity_id="e1", loyalty_cost=400, ltv_orders=1000, refunds=0, as_of=None):
    as_of = as_of or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "as_of": as_of,
        "orders": [
            {
                "entity_id": entity_id,
                "order_id": "o1",
                "ts": as_of,
                "amount_minor": ltv_orders,
                "currency": "USD",
                "status": "paid",
            }
        ],
        "refunds": (
            []
            if refunds == 0
            else [
                {
                    "entity_id": entity_id,
                    "order_id": "o1",
                    "ts": as_of,
                    "amount_minor": refunds,
                    "currency": "USD",
                }
            ]
        ),
        "loyalty_ledger": [
            {
                "entity_id": entity_id,
                "ts": as_of,
                "direction": "burn",
                "value_minor": loyalty_cost,
                "program_id": "default",
            }
        ],
        "lifecycle": [
            {
                "entity_id": entity_id,
                "created_at": "2025-01-01T00:00:00Z",
                "last_active_at": as_of,
            }
        ],
    }


def test_schema_and_missing_feeds():
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=None, program_config=_cfg()
    )
    assert out["schema_id"] == SCHEMA_ID
    assert out["status"] == "feeds_missing"
    assert out["gates"]["order"]["eligible"] is None
    assert out["policy"]["order_decision_untouched"] is True


def test_incomplete_without_ledger():
    snap = _complete_feeds()
    del snap["loyalty_ledger"]
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=snap, program_config=_cfg()
    )
    assert out["status"] == "feeds_incomplete"
    assert out["gates"]["dispatch"]["eligible"] is None


def test_config_missing():
    out = evaluate_loyalty_economics(
        entity_id="e1", feed_snapshot=_complete_feeds(), program_config=None
    )
    assert out["status"] == "config_missing"


def test_ratio_breach_order_ineligible_dispatch_may_differ():
    # loyalty 400 / LTV 1000 = 0.4 > 0.25
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=400, ltv_orders=1000),
        program_config=_cfg(),
        scope={"kind": "program", "id": "default"},
    )
    assert out["status"] in ("ok", "partial_derived")
    assert out["metrics"]["loyalty_ltv_ratio"] == 0.4
    assert out["gates"]["order"]["eligible"] is False
    assert out["gates"]["order"]["status"] == "ok"
    # v1 default policy: dispatch also ineligible on ratio breach (churn weight same)
    assert out["gates"]["dispatch"]["eligible"] is False


def test_healthy_ratio_all_eligible():
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=50, ltv_orders=1000),
        program_config=_cfg(),
    )
    assert out["gates"]["order"]["eligible"] is True
    assert out["gates"]["redeem"]["eligible"] is True
    assert out["gates"]["dispatch"]["eligible"] is True


def test_hysteresis_requires_dwell():
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    # Currently healthy ratio but prior ineligible without enough dwell
    prior = {
        "ineligible_since": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "restore_band_since": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(loyalty_cost=50, ltv_orders=1000, as_of=now.isoformat().replace("+00:00", "Z")),
        program_config=_cfg(min_dwell_seconds=86400),
        now=now,
        prior_gate_state=prior,
    )
    assert out["gates"]["order"]["eligible"] is False
    assert any("dwell" in r for r in out["gates"]["order"]["reasons"])


def test_vip_escape():
    out = evaluate_loyalty_economics(
        entity_id="vip1",
        feed_snapshot=_complete_feeds(entity_id="vip1", loyalty_cost=900, ltv_orders=1000),
        program_config=_cfg(vip_entity_ids=["vip1"]),
    )
    assert out["gates"]["order"]["eligible"] is True
    assert any("vip" in r for r in out["gates"]["order"]["reasons"])


def test_cluster_unit_when_peers():
    out = evaluate_loyalty_economics(
        entity_id="e1",
        feed_snapshot=_complete_feeds(),
        program_config=_cfg(),
        cluster_entity_ids=["e1", "e2"],
    )
    assert out["unit"] == "cluster"


@pytest.fixture
async def loyalty_eval_client():
    """Minimal evaluate client capturing audit snapshot for loyalty gates."""
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
            mock_redis.merge_tags = AsyncMock(return_value=[])
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
                                    return_value=None,
                                ):
                                    with patch(
                                        "decision_api.main._fetch_location_evaluation_wrapped",
                                        new_callable=AsyncMock,
                                        return_value=None,
                                    ):
                                        from decision_api.main import app, get_session

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


@pytest.mark.asyncio
async def test_evaluate_attaches_loyalty_gates_without_deny(loyalty_eval_client):
    """Evaluate audit includes loyalty gates; ratio breach does not deny order."""
    c = loyalty_eval_client
    entity_id = "u-loyalty"
    r = await c.post(
        "/v1/decisions/evaluate",
        json={
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": entity_id,
            "payload": {},
            "metadata": {
                "loyalty_feed_snapshot": _complete_feeds(
                    entity_id=entity_id, loyalty_cost=400, ltv_orders=1000
                ),
                "loyalty_program_config": _cfg(),
            },
        },
        headers={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] != "deny"
    assert len(c._captured) == 1
    snap = c._captured[0].payload_snapshot
    gates = snap.get("loyalty_economics_gates")
    assert gates is not None
    assert gates["schema_id"] == SCHEMA_ID
    assert gates["gates"]["order"]["eligible"] is False
    assert gates["policy"]["order_decision_untouched"] is True
    assert "loyalty:order_benefit_ineligible" in body["tags"]
