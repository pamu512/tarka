"""Orchestrator runs graph ingest + DuckDB append after successful rule evaluation (async sidecars).

**Manual gate (JanusGraph + DuckDB)** — with ``GRAPH_BACKEND=janusgraph``, ``GREMLIN_REMOTE_URL`` set,
and the orchestrator running locally:

1. ``POST /v1/ingest`` with ``metadata.user_id``, ``metadata.billing_address`` (or ``graph_address``),
   ``country``, ``amount``, ``timestamp``, ``entity_id``.
2. Gremlin console: ``g.V().has('User','user_id','<id>').out('LIVES_AT').values('line1')``
3. ``GET /v1/analytics/transactions?limit=20`` — confirm a row whose ``entity_id`` matches the ingest.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
from orchestrator.graph.client import GraphClient  # noqa: E402
from orchestrator.main import create_app  # noqa: E402


class _RecordingGraphClient(GraphClient):
    def __init__(self) -> None:
        self.transactions: list[TransactionSchema] = []

    async def ingest_transaction(self, transaction: TransactionSchema) -> None:
        self.transactions.append(transaction)

    async def users_connected_to_ip(self, ip: str) -> list[str]:
        return []

    async def get_graph_signals(self, entity_id: str) -> dict:
        return {"entity_ref": entity_id, "stub": True}

    async def device_hardware_risk(
        self,
        device_id: str,
        *,
        current_user_id: str | None = None,
    ) -> dict[str, object]:
        _ = current_user_id
        return {
            "device_id": device_id,
            "linked_to_blocked_node": False,
            "blocked_user_count_on_device": 0,
        }

    async def close(self) -> None:
        return None

    async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, object]:
        _ = anchor_user_id
        return {
            "found": False,
            "anchor_user_id": anchor_user_id,
            "network_user_ids": [],
            "network_transaction_ids": [],
            "network_device_ids": [],
            "network_ip_addresses": [],
            "blocked_device_touch_count": 0,
            "neighbor_node_count": 0,
            "edges_summary": [],
            "backend": "stub",
        }


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = "{}"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _EvalOnlyAsyncClient:
    async def __aenter__(self) -> _EvalOnlyAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse({"actions": ["FLAG"], "transaction_id": str(UUID(int=7))})
        raise AssertionError(f"unexpected post url: {url!r}")


@pytest.fixture
def recording_graph_client() -> _RecordingGraphClient:
    return _RecordingGraphClient()


def test_v1_ingest_invokes_graph_client_after_evaluate(
    monkeypatch: pytest.MonkeyPatch,
    recording_graph_client: _RecordingGraphClient,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _EvalOnlyAsyncClient())

    duck = DuckAnalyticsProvider()
    duck.load()

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        graph_client_override=recording_graph_client,
        duck_analytics_provider=duck,
    )
    body = {
        "entity_id": "22222222-2222-2222-2222-222222222222",
        "amount": 42.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "country": "US",
        "metadata": {"user_id": "user_1", "ip": "ip_A"},
    }
    with TestClient(app) as client:
        r = client.post("/v1/ingest", json=body)
        assert r.status_code == 200
        time.sleep(0.15)
        snap = client.get("/v1/analytics/transactions?limit=50")
    assert snap.status_code == 200
    rows = snap.json()["rows"]
    assert any(str(r.get("entity_id")) == "22222222-2222-2222-2222-222222222222" for r in rows)

    assert len(recording_graph_client.transactions) == 1
    ingested = recording_graph_client.transactions[0]
    assert str(ingested.entity_id) == "22222222-2222-2222-2222-222222222222"
    assert ingested.metadata.get("user_id") == "user_1"
    assert ingested.metadata.get("ip") == "ip_A"
