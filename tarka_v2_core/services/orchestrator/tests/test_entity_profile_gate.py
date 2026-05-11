"""Gate: Entity Explorer profile merges Postgres lifecycle, graph fragment, and DuckDB metrics."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def _skip_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_ENTITY_PROFILE_SKIP_SHADOW", "1")


def test_entity_profile_unifies_postgres_graph_duck() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    from ingestor.manifest_schema import TransactionSchema  # noqa: E402
    from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
    from orchestrator.graph.client import GraphClient  # noqa: E402
    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    class _GraphStub(GraphClient):
        async def ingest_transaction(self, transaction: object) -> None:
            return None

        async def users_connected_to_ip(self, ip: str) -> list[str]:
            return []

        async def get_graph_signals(self, entity_id: str) -> dict[str, object]:
            return {}

        async def device_hardware_risk(
            self,
            device_id: str,
            *,
            current_user_id: str | None = None,
        ) -> dict[str, object]:
            return {}

        async def close(self) -> None:
            return None

        async def two_hop_neighbor_network(self, anchor_user_id: str) -> dict[str, object]:
            uid = anchor_user_id.strip()
            return {
                "found": True,
                "anchor_user_id": uid,
                "network_user_ids": [uid, "peer-neighbor"],
                "network_transaction_ids": [],
                "network_device_ids": ["device-aa"],
                "network_ip_addresses": ["198.51.100.2"],
                "blocked_device_touch_count": 0,
                "neighbor_node_count": 4,
                "edges_summary": [],
                "backend": "janusgraph",
            }

    uid = "u_market_entity_gate"
    entity_id = "55555555-5555-5555-5555-555555555555"
    duck = DuckAnalyticsProvider()
    duck.load()
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=42.5,
            timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC),
            metadata={
                "user_id": uid,
                "listing_id": "LST-77",
                "promo_applied": "true",
                "promo_outcome": "success",
            },
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=10.0,
            timestamp=datetime(2026, 7, 1, 13, 0, 0, tzinfo=UTC),
            metadata={"user_id": uid, "listing_id": "LST-88", "promo_applied": "false"},
        ),
    )
    # Prompt 123: same graph device as stub ``device-aa`` — cluster loss spans sessions + other accounts.
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=100.0,
            timestamp=datetime(2026, 7, 1, 14, 0, 0, tzinfo=UTC),
            metadata={
                "user_id": "bad_actor_gate",
                "device_id": "device-aa",
                "session_id": "sess-cluster-1",
            },
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=200.0,
            timestamp=datetime(2026, 7, 1, 14, 1, 0, tzinfo=UTC),
            metadata={"user_id": "other_user_gate", "session_id": "sess-cluster-1"},
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=50.0,
            timestamp=datetime(2026, 7, 1, 14, 2, 0, tzinfo=UTC),
            metadata={
                "user_id": "other_user_gate",
                "device_id": "device-aa",
                "session_id": "sess-cluster-2",
            },
        ),
    )
    duck.append_transaction(
        TransactionSchema(
            entity_id=uuid.uuid4(),
            amount=75.0,
            timestamp=datetime(2026, 7, 1, 14, 3, 0, tzinfo=UTC),
            metadata={"user_id": "third_party_gate", "session_id": "sess-cluster-2"},
        ),
    )

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        graph_client_override=_GraphStub(),
        duck_analytics_provider=duck,
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=entity_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="entity-profile-anchor",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            log = AuditLog(
                case_id=entity_id,
                action_taken="{}",
                agent_notes=None,
                code_executed=None,
                timestamp=datetime(2026, 7, 2, 10, 0, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=str(uuid.uuid4()),
                    transaction_id=int(log.id),
                    user_link_key=uid,
                    entity_id=entity_id,
                    status=CaseStatus.UNDER_REVIEW.value,
                    priority=42,
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        r = client.get(f"/v1/marketplace/users/{uid}/entity-profile")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == uid
    assert body["lifecycle_case"]["status"] == "UNDER_REVIEW"
    assert body["lifecycle_case"]["source"] == "postgres"
    assert body["graph_fragment"]["backend"] == "janusgraph"
    assert "device-aa" in body["graph_fragment"]["network_device_ids"]
    assert "198.51.100.2" in body["graph_fragment"]["network_ip_addresses"]
    assert body["graph_viz"]["links"], body["graph_viz"]
    dm = body["duckdb_metrics"]
    assert dm["txn_count"] == 2
    assert dm["listing_count"] == 2
    assert dm["total_spend"] == pytest.approx(52.5)
    assert dm["promo_success_rate"] == pytest.approx(1.0)
    assert dm["cluster_loss"] == pytest.approx(425.0)
    assert dm["cluster_loss_txn_count"] == 4
    assert dm["cluster_loss_session_count"] == 2
    assert "device-aa" in dm["cluster_loss_device_scope"]
    assert body["data_sources"]["postgres_case_row"] is True
    assert body["data_sources"]["duckdb"] is True
    assert body["data_sources"]["graph_neighbors_found"] is True
    assert body["shadow_executive_summary"]["skipped"] is True
