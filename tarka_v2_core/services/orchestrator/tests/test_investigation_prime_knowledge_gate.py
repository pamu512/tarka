"""Gate: Knowledge Drop prime returns PENDING_ACTION conflict when entity matches lifecycle case."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_prime_knowledge_pending_action_conflict_gate() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app
    from orchestrator.models.cases import CaseORM, CaseStatus
    from tarka_shared.audit_trail import AuditLog, Case
    from tarka_shared.case_status import DEFAULT_CASE_STATUS
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

    entity_id = "44444444-4444-4444-4444-444444444444"
    db_url = "sqlite+aiosqlite:///:memory:"
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url=db_url,
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=entity_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="knowledge-drop-anchor",
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
                timestamp=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=str(uuid.uuid4()),
                    transaction_id=int(log.id),
                    user_link_key="seed-user",
                    entity_id=entity_id,
                    status=CaseStatus.PENDING_ACTION.value,
                    priority=5,
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        raw = f"Dispute paperwork references transaction {entity_id}\n".encode("utf-8")
        r = client.post(
            "/v1/investigation/prime",
            files={"file": ("gate.txt", raw, "text/plain")},
        )

    assert r.status_code == 200, r.text
    data = r.json()
    rows = [k for k in data.get("knowledge", []) if k.get("detected_id") == entity_id]
    assert rows, data
    assert rows[0]["pending_action_conflict"] is True
    assert rows[0]["active_investigation_count"] >= 1
