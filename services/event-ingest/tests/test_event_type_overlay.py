"""Tenant event-type overlay at the ingest plane (split-brain fix).

Covers: tenant-added type accepted at POST /v1/events, /v1/events/batch,
/v1/ingest/dynamic; fail-closed on fetch error; seed hit never consults the
overlay; overlay client caching semantics.
"""

import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("NATS_URL", "nats://localhost:4222")

import httpx
import pytest
from event_ingest import event_type_overlay, main
from event_ingest.config import settings
from fastapi.testclient import TestClient

TENANT_TYPE = "loyalty_redemption"


@pytest.fixture
def mock_js():
    js = AsyncMock()
    js.publish = AsyncMock(return_value=type("Ack", (), {"seq": 1})())
    return js


@pytest.fixture
def client(mock_js, monkeypatch):
    monkeypatch.delenv("TARKA_EVENT_TYPES", raising=False)
    with patch("event_ingest.main._connect_nats", new_callable=AsyncMock) as mock_connect:
        nc = AsyncMock()
        nc.is_connected = True
        nc.drain = AsyncMock()
        mock_connect.return_value = (nc, mock_js)
        with patch("event_ingest.main.asyncio.create_task"):
            with TestClient(main.app) as c:
                yield c


def _overlay(names):
    async def _fake(http, tenant_id):
        return frozenset(names)

    return _fake


def _valid_event(event_type=TENANT_TYPE):
    return {
        "tenant_id": "acme",
        "entity_id": "u1",
        "event_type": event_type,
        "payload": {"amount": 10},
    }


# --- POST /v1/events ---------------------------------------------------------


def test_single_event_tenant_overlay_type_accepted(client):
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([TENANT_TYPE])):
        r = client.post("/v1/events", json=_valid_event())
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True


def test_single_event_overlay_miss_still_422(client):
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([])):
        r = client.post("/v1/events", json=_valid_event())
    assert r.status_code == 422
    assert "ingest_event_type_invalid" in r.json()["detail"]["reason_codes"]


def test_single_event_overlay_fetch_error_fails_closed(client):
    async def _boom(http, tenant_id):
        raise ConnectionError("decision-api down")

    with patch.object(main, "tenant_overlay_names", side_effect=_boom):
        r = client.post("/v1/events", json=_valid_event())
    assert r.status_code == 422
    assert "ingest_event_type_invalid" in r.json()["detail"]["reason_codes"]


def test_seed_hit_never_consults_overlay(client):
    async def _must_not_be_called(http, tenant_id):
        raise AssertionError("overlay consulted for a seed type")

    with patch.object(main, "tenant_overlay_names", side_effect=_must_not_be_called):
        r = client.post("/v1/events", json=_valid_event("login"))
    assert r.status_code == 200, r.text


def test_overlay_disabled_flag_preserves_old_behavior(client, monkeypatch):
    monkeypatch.setattr(settings, "event_type_overlay_enabled", False)
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([TENANT_TYPE])):
        r = client.post("/v1/events", json=_valid_event())
    assert r.status_code == 422


def test_malformed_shape_not_rescued_by_overlay(client):
    # Invalid event_type *shape* (uppercase) must 422 without consulting overlay.
    async def _must_not_be_called(http, tenant_id):
        raise AssertionError("overlay consulted for a shape-invalid type")

    with patch.object(main, "tenant_overlay_names", side_effect=_must_not_be_called):
        r = client.post("/v1/events", json=_valid_event("Not_A_Type"))
    assert r.status_code == 422


# --- POST /v1/events/batch ---------------------------------------------------


def test_batch_item_tenant_overlay_type_accepted(client):
    body = {
        "events": [
            _valid_event("login"),
            _valid_event(TENANT_TYPE),
        ]
    }
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([TENANT_TYPE])):
        r = client.post("/v1/events/batch", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 2
    assert r.json()["results"][1]["seq"] == 1


def test_batch_item_overlay_miss_422s_whole_batch(client):
    body = {"events": [_valid_event(TENANT_TYPE)]}
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([])):
        r = client.post("/v1/events/batch", json=body)
    assert r.status_code == 422


# --- POST /v1/ingest/dynamic -------------------------------------------------


def test_dynamic_tenant_overlay_type_mapped(client):
    raw = {
        "tenantId": "acme",
        "userId": "u1",
        "type": TENANT_TYPE,
        "amount": 10,
    }
    with patch.object(main, "tenant_overlay_names", side_effect=_overlay([TENANT_TYPE])):
        r = client.post("/v1/ingest/dynamic", json=raw)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True


def test_dynamic_missing_fields_stay_mapping_pending(client):
    # entity_id absent -> candidates not present -> no overlay consult, 422.
    async def _must_not_be_called(http, tenant_id):
        raise AssertionError("overlay consulted without entity")

    raw = {"tenantId": "acme", "type": TENANT_TYPE}
    with patch.object(main, "tenant_overlay_names", side_effect=_must_not_be_called):
        r = client.post("/v1/ingest/dynamic", json=raw)
    assert r.status_code == 422
    assert r.json()["mapping_pending"] is True


# --- overlay client unit tests -----------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, response=None, exc=None):
        self._response = response or _FakeResponse(payload={"names": []})
        self._exc = exc
        self.calls = 0

    async def get(self, *args, **kwargs):
        self.calls += 1
        if self._exc:
            raise self._exc
        return self._response


@pytest.fixture(autouse=True)
def _clean_overlay_state():
    event_type_overlay._reset_for_tests()
    yield
    event_type_overlay._reset_for_tests()


async def test_client_parses_names():
    http = _FakeResponse(payload={"names": [TENANT_TYPE, "other"]})
    names = await event_type_overlay.tenant_overlay_names(_FakeHttp(http), "acme")
    assert names == frozenset({TENANT_TYPE, "other"})


async def test_client_caches_per_tenant():
    http = _FakeHttp(_FakeResponse(payload={"names": [TENANT_TYPE]}))
    fake = _FakeHttp(http)
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    assert fake.calls == 1  # TTL cache


async def test_client_negative_cache_bounds_burst():
    fake = _FakeHttp()  # empty names
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    assert fake.calls == 1  # empty result cached (2s negative cache)


async def test_client_fail_closed_backoff():
    fake = _FakeHttp(exc=ConnectionError("down"))
    names = await event_type_overlay.tenant_overlay_names(fake, "acme")
    assert names == frozenset()
    await event_type_overlay.tenant_overlay_names(fake, "acme")
    assert fake.calls == 1  # backoff window suppresses refetch
