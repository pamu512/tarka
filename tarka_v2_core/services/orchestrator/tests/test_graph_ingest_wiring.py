"""Orchestrator enqueues graph + velocity outbox tasks after successful rule evaluation.

**Manual gate (JanusGraph + outbox relay)** — with ``GRAPH_BACKEND=janusgraph``, ``GREMLIN_REMOTE_URL`` set,
outbox relay running, and the orchestrator running locally:

1. ``POST /v1/ingest`` with ``metadata.user_id``, ``metadata.billing_address`` (or ``graph_address``),
   ``country``, ``amount``, ``timestamp``, ``entity_id``.
2. Confirm ``tarka_outbox`` rows ``GRAPH_INGEST`` + ``VELOCITY_UPDATE`` for the entity id.
3. After relay processes ``GRAPH_INGEST``, Gremlin console:
   ``g.V().has('User','user_id','<id>').out('LIVES_AT').values('line1')``
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.graph.client import GraphClient  # noqa: E402
from orchestrator.main import create_app  # noqa: E402
from orchestrator.models.outbox import (  # noqa: E402
    OUTBOX_EVENT_GRAPH_INGEST,
    OUTBOX_EVENT_VELOCITY_UPDATE,
    OutboxORM,
    OutboxStatus,
)


class _RecordingGraphClient(GraphClient):
    def __init__(self) -> None:
        self.transactions: list[object] = []

    async def ingest_transaction(self, transaction: object) -> None:
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
    def __init__(self, *, entity_id: str) -> None:
        self._entity_id = entity_id

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
            return _DummyUpstreamResponse(
                {
                    "actions": ["FLAG"],
                    "transaction_id": self._entity_id,
                    "evaluation_trace": [
                        {
                            "rule_id": "22222222-2222-2222-2222-222222222222",
                            "rule_name": "flag_rule",
                            "priority": 5,
                            "matched": True,
                            "action": "FLAG",
                        },
                    ],
                    "blocking_rule_id": None,
                },
            )
        raise AssertionError(f"unexpected post url: {url!r}")


@pytest.fixture
def recording_graph_client() -> _RecordingGraphClient:
    return _RecordingGraphClient()


def test_v1_ingest_enqueues_graph_and_velocity_outbox_tasks(
    monkeypatch: pytest.MonkeyPatch,
    recording_graph_client: _RecordingGraphClient,
) -> None:
    entity_id = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: _EvalOnlyAsyncClient(entity_id=entity_id)
    )

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        graph_client_override=recording_graph_client,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    body = {
        "entity_id": entity_id,
        "amount": 42.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "country": "US",
        "metadata": {"user_id": "user_1", "ip": "ip_A", "canvas_fingerprint": "cd" * 32},
    }
    with TestClient(app) as client:
        r = client.post("/v1/ingest", json=body)
        assert r.status_code == 200

    async def _fetch_outbox() -> list[OutboxORM]:
        fac = app.state.audit_session_factory
        async with fac() as session:
            rows = (
                await session.scalars(
                    select(OutboxORM)
                    .where(
                        OutboxORM.idempotency_key.like(f"graph_ingest:{entity_id}:%")
                        | OutboxORM.idempotency_key.like(f"velocity_update:{entity_id}:%"),
                    )
                    .order_by(OutboxORM.event_type.asc())
                )
            ).all()
            return list(rows)

    rows = asyncio.run(_fetch_outbox())
    assert len(rows) == 2
    by_type = {row.event_type: row for row in rows}
    graph_row = by_type[OUTBOX_EVENT_GRAPH_INGEST]
    vel_row = by_type[OUTBOX_EVENT_VELOCITY_UPDATE]
    assert graph_row.status == OutboxStatus.PENDING.value
    assert vel_row.status == OutboxStatus.PENDING.value
    assert graph_row.idempotency_key.startswith(f"graph_ingest:{entity_id}:")
    assert graph_row.payload["entity_id"] == entity_id
    assert graph_row.payload["transaction_id"] == entity_id
    assert "22222222-2222-2222-2222-222222222222" in graph_row.payload["resolved_rules"]
    assert graph_row.payload["edge_transaction_payload_envelope"]["metadata"]["user_id"] == "user_1"
    assert vel_row.idempotency_key.startswith(f"velocity_update:{entity_id}:")
    assert vel_row.payload["entity_id"] == entity_id
    assert vel_row.payload["amount_cents"] == 4200
    assert vel_row.payload["client_browser_metadata_context"]["canvas_fingerprint"] == "cd" * 32
    assert len(recording_graph_client.transactions) == 0
