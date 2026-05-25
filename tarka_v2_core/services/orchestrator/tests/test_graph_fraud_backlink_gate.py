"""
Gate (Prompt 115): resolving a lifecycle case as ``RESOLVED_FRAUD`` sets ``is_fraud=true`` on the User vertex.

**Automated gate** — requires a live Gremlin endpoint, ``gremlinpython``, and JanusGraph configured like ingest::

    export GRAPH_BACKEND=janusgraph
    export GREMLIN_REMOTE_URL=ws://127.0.0.1:8182/gremlin
    pytest tarka_v2_core/services/orchestrator/tests/test_graph_fraud_backlink_gate.py -q

**Manual Gremlin console check** (after ``PUT /v1/cases/{id}/status`` with ``status: RESOLVED_FRAUD`` for a case
whose ``lifecycle_cases.user_link_key`` matches graph ``User.user_id``)::

    g.V().has('User','user_id','<user_link_key>').values('is_fraud')
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_resolve_fraud_sets_janus_user_is_fraud() -> None:
    from ingestor.manifest_schema import TransactionSchema  # noqa: E402

    from orchestrator.graph.client import JanusGraphClient  # noqa: E402
    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from orchestrator.workers.graph_sync import read_janus_user_is_fraud_values  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    jc = JanusGraphClient.try_from_env()
    if jc is None:
        pytest.skip(
            "JanusGraph Gremlin client unavailable (install gremlinpython, set GREMLIN_REMOTE_URL, "
            "ensure graph host is reachable)",
        )

    user_link = f"gate_graph_fraud_115_{uuid.uuid4().hex[:12]}"
    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())
    txn_id = str(uuid.uuid4())

    async def _ingest_user_vertex() -> None:
        await jc.ingest_transaction(
            TransactionSchema(
                entity_id=UUID(txn_id),
                amount=9.0,
                timestamp=datetime(2026, 5, 10, 14, 0, 0, tzinfo=UTC),
                metadata={"user_id": user_link, "ip": "10.115.0.1"},
            ),
        )

    asyncio.run(_ingest_user_vertex())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        graph_client_override=jc,
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="shadow-anchor-115",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            log = AuditLog(
                case_id=shadow_case_id,
                action_taken="{}",
                agent_notes=None,
                code_executed=None,
                timestamp=datetime(2026, 5, 10, 14, 1, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=case_uuid,
                    transaction_id=int(log.id),
                    user_link_key=user_link,
                    entity_id=txn_id,
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())

        r = client.put(
            f"/v1/cases/{case_uuid}/status",
            json={
                "status": CaseStatus.RESOLVED_FRAUD.value,
                "reason_code": "GATE_FRAUD_DISPOSITION",
            },
            headers={"X-Auth-Token": "gate-token-115"},
        )
        assert r.status_code == 200, r.text

        after = read_janus_user_is_fraud_values(jc, user_link)
        assert any(v is True or str(v).lower() == "true" for v in after), after
