"""Author catalog GET + AI allow-list."""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.author_catalog import ai_allowed_fields, build_author_catalog
from decision_api.rule_api import router as rules_router


def test_catalog_growth_empty_when_graph_off():
    cat = build_author_catalog(graph_url="", growth_windows=[{"window": "1h", "threshold": 5}])
    assert cat["growth"] == []
    names = {r["name"] for r in cat["redis"]}
    assert "event_count_7d" in names
    assert "avg_amount_1h" in names
    assert {h["etype"] for h in cat["hops"]} == {
        "USES_DEVICE",
        "HAS_EMAIL",
        "HAS_PHONE",
        "HAS_CARD",
        "HAS_LIST",
    }


def test_catalog_growth_from_policy_when_graph_on():
    cat = build_author_catalog(
        graph_url="http://graph.test",
        growth_windows=[{"window": "1h", "threshold": 5}, {"window": "24h", "threshold": 15}],
    )
    assert {g["name"] for g in cat["growth"]} == {"relation_growth_1h", "relation_growth_24h"}
    by_name = {g["name"]: g for g in cat["growth"]}
    assert by_name["relation_growth_1h"] == {
        "name": "relation_growth_1h",
        "kind": "growth",
        "window": "1h",
        "threshold": 5,
    }


def test_ai_allow_list_keeps_aliases_and_canonical():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    allowed = ai_allowed_fields(cat)
    assert "tx_count_1h" in allowed
    assert "event_count_7d" in allowed
    assert "rate" not in allowed
    assert "baseline_ratio" not in allowed


def test_validate_ai_pack_uses_catalog_allow_list(monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "graph_service_url", "")
    pack = {
        "mode": "shadow",
        "is_ai_authored": True,
        "rules": [
            {
                "id": "r1",
                "score_delta": 10,
                "when": [{"field": "tx_count_1h", "op": "gte", "value": 5}],
            }
        ],
    }
    assert rule_api._validate_ai_authored_pack(pack) == []
    pack["rules"][0]["when"][0]["field"] = "rate"
    errors = rule_api._validate_ai_authored_pack(pack)
    assert any("unknown field" in e for e in errors)


def test_catalog_payload_is_frozen_extras():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    assert [p["name"] for p in cat["payload"]] == [
        "amount",
        "currency",
        "device_type",
        "is_bot",
        "is_emulator",
        "is_rooted",
        "is_vpn",
        "session_duration",
        "country",
        "ip_is_proxy",
        "distinct_countries_7d",
        "email_domain",
    ]


def test_redis_row_has_window_token_and_optional_field():
    cat = build_author_catalog(graph_url="", growth_windows=None)
    by_name = {r["name"]: r for r in cat["redis"]}
    one_h = by_name["event_count_1h"]
    assert one_h["kind"] == "event_count"
    assert one_h["window"] == "1h"
    assert one_h["window_seconds"] == 3600
    assert "field" not in one_h
    avg = by_name["avg_amount_1h"]
    assert avg["field"] == "amount"
    assert avg["kind"] == "avg"


def test_author_catalog_route_is_registered_above_filename():
    paths = [
        r.path
        for r in rules_router.routes
        if isinstance(r, APIRoute) and "GET" in r.methods
    ]
    assert "/v1/rules/author-catalog" in paths
    assert paths.index("/v1/rules/author-catalog") < paths.index("/v1/rules/{filename}")


@pytest.fixture
async def rules_client():
    app = FastAPI()
    app.include_router(rules_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_get_author_catalog_not_swallowed_as_filename(rules_client, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "graph_service_url", "")
    r = await rules_client.get("/v1/rules/author-catalog")
    assert r.status_code == 200
    data = r.json()
    assert "redis" in data
    assert "growth" in data
    assert "hops" in data
    assert "payload" in data
    assert data["growth"] == []


@pytest.mark.asyncio
async def test_get_author_catalog_does_not_require_counters_token(rules_client, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "graph_service_url", "")
    r = await rules_client.get("/v1/rules/author-catalog")
    assert r.status_code == 200
    assert r.json()["hops"][0]["etype"] == "USES_DEVICE"


@pytest.mark.asyncio
async def test_get_author_catalog_growth_from_graph_policy(rules_client, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "graph_service_url", "http://graph.test")

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "windows": [
                    {"window": "1h", "threshold": 5},
                    {"window": "24h", "threshold": 15},
                ]
            }

    monkeypatch.setattr(rule_api.httpx, "get", lambda *a, **k: _Resp())
    r = await rules_client.get("/v1/rules/author-catalog")
    assert r.status_code == 200
    assert {g["name"] for g in r.json()["growth"]} == {
        "relation_growth_1h",
        "relation_growth_24h",
    }


@pytest.mark.asyncio
async def test_get_author_catalog_growth_empty_when_policy_fails(rules_client, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "graph_service_url", "http://graph.test")

    def _boom(*_a, **_k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(rule_api.httpx, "get", _boom)
    r = await rules_client.get("/v1/rules/author-catalog")
    assert r.status_code == 200
    assert r.json()["growth"] == []
