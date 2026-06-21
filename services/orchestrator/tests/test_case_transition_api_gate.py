"""Gate (Prompt 112): ``PUT /v1/cases/{id}/status`` appends a ``case_history`` row."""

from __future__ import annotations

import asyncio
import json
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
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_put_case_status_creates_case_history_row(tmp_path: Path) -> None:
    import models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402
    from models.cases import CaseHistoryORM, CaseORM, CaseStatus  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())

    audit_db = tmp_path / "audit_case_transition.db"
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url=f"sqlite+aiosqlite:///{audit_db}",
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

        async def _exercise() -> dict[str, object]:
            await _seed()
            r = client.put(
                f"/v1/cases/{case_uuid}/status",
                json={"status": "UNDER_REVIEW", "reason_code": "GATE_ANALYST_REVIEW"},
                headers={"X-Auth-Token": "gate-secret-token-112"},
            )
            assert r.status_code == 200, r.text
            return r.json()

        data = asyncio.run(_exercise())
        assert data["case_id"] == case_uuid
        assert data["status"] == "UNDER_REVIEW"
        assert isinstance(data["history_row_id"], int)
        assert isinstance(data["audit_log_id"], int)

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
            assert row.audit_log_id is not None
            assert row.from_status == CaseStatus.OPEN.value
            assert row.to_status == CaseStatus.UNDER_REVIEW.value
            assert row.reason_code == "GATE_ANALYST_REVIEW"
            assert row.auth_token_fingerprint is not None
            assert len(row.auth_token_fingerprint) == 64

            audit = await s.get(AuditLog, int(row.audit_log_id))
            assert audit is not None
            body = json.loads(audit.action_taken)
            assert body["source"] == "lifecycle_case_status_transition"
            assert body["lifecycle_case_id"] == case_uuid
            assert body["old_status"] == CaseStatus.OPEN.value
            assert body["new_status"] == CaseStatus.UNDER_REVIEW.value
            assert body["justification"] == "GATE_ANALYST_REVIEW"
            assert body["actor_id"] == row.auth_token_fingerprint

        asyncio.run(_verify_history())


def test_put_case_status_terminal_enqueues_shadow_retro_tag_outbox() -> None:
    import models.cases  # noqa: F401, PLC0415
    import models.outbox  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402
    from models.cases import CaseORM, CaseStatus  # noqa: E402
    from models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

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
                    entity_id=entity_id,
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
                "status": "RESOLVED_FRAUD",
                "reason_code": "GATE_FINAL_FRAUD",
                "analyst_notes": "Confirmed mule pattern from device graph.",
            },
            headers={"X-Auth-Token": "gate-secret-token-shadow-retro"},
        )
        assert r.status_code == 200, r.text

        async def _fetch_outbox() -> OutboxORM | None:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as session:
                return await session.scalar(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG),
                )

        outbox_row = asyncio.run(_fetch_outbox())
        assert outbox_row is not None
        assert outbox_row.idempotency_key == f"shadow_tag_case:{case_uuid}:RESOLVED_FRAUD"
        assert outbox_row.payload["entity_id"] == entity_id
        assert outbox_row.payload["case_id"] == case_uuid
        assert outbox_row.payload["new_status"] == "RESOLVED_FRAUD"
        assert outbox_row.payload["analyst_notes"] == "Confirmed mule pattern from device graph."


def test_put_case_status_non_terminal_skips_shadow_retro_tag_outbox() -> None:
    import models.cases  # noqa: F401, PLC0415
    import models.outbox  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402
    from models.cases import CaseORM, CaseStatus  # noqa: E402
    from models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM  # noqa: E402
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
            headers={"X-Auth-Token": "gate-secret-token-shadow-retro"},
        )
        assert r.status_code == 200, r.text

        async def _count_shadow_retro() -> int:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as session:
                return int(
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxORM)
                        .where(OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG),
                    )
                    or 0,
                )

        assert asyncio.run(_count_shadow_retro()) == 0


def test_lifecycle_case_for_update_stmt_uses_postgresql_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    from case_transition_api import _lifecycle_case_for_update_stmt

    stmt = _lifecycle_case_for_update_stmt("case-uuid").with_for_update()
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled.upper()
    assert "lifecycle_cases" in compiled.lower()


def test_put_case_status_requires_auth_header() -> None:
    import models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402

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
