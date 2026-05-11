"""Gate (Prompt 112): ``PUT /v1/cases/{id}/status`` appends a ``case_history`` row."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_put_case_status_creates_case_history_row() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseHistoryORM, CaseORM, CaseStatus  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="shadow-anchor",
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
                timestamp=datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=case_uuid,
                    transaction_id=int(log.id),
                    user_link_key="u_gate_case",
                    entity_id=str(uuid.uuid4()),
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        r = client.put(
            f"/v1/cases/{case_uuid}/status",
            json={"status": "UNDER_REVIEW", "reason_code": "GATE_ANALYST_REVIEW"},
            headers={"X-Auth-Token": "gate-secret-token-112"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["case_id"] == case_uuid
        assert data["status"] == "UNDER_REVIEW"
        assert isinstance(data["history_row_id"], int)

        async def _verify_history() -> None:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as s:
                n = await s.scalar(select(func.count()).select_from(CaseHistoryORM))
                row = await s.scalar(
                    select(CaseHistoryORM).where(CaseHistoryORM.id == int(data["history_row_id"])),
                )
            assert n == 1
            assert row is not None
            assert row.case_id == case_uuid
            assert row.audit_log_id is None
            assert row.from_status == CaseStatus.OPEN.value
            assert row.to_status == CaseStatus.UNDER_REVIEW.value
            assert row.reason_code == "GATE_ANALYST_REVIEW"
            assert row.auth_token_fingerprint is not None
            assert len(row.auth_token_fingerprint) == 64

        asyncio.run(_verify_history())


def test_put_case_status_requires_auth_header() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    with TestClient(app) as client:
        r = client.put(
            f"/v1/cases/{uuid.uuid4()}/status",
            json={"status": "OPEN", "reason_code": "x"},
        )
    assert r.status_code == 422
