"""Gate: terminal case dispositions persist ``normalized_labels`` rows atomically."""

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
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _seed_open_case(app, *, case_uuid: str, shadow_case_id: str, entity_id: str) -> None:
    import models.cases  # noqa: F401, PLC0415
    import models.normalized_labels  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from models.cases import CaseORM, CaseStatus  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    async def _run() -> None:
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

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("resolved_status", "expected_class"),
    [
        ("RESOLVED_FRAUD", "FRAUD"),
        ("RESOLVED_LEGIT", "LEGITIMATE"),
    ],
)
def test_put_case_status_resolved_creates_normalized_label(
    resolved_status: str,
    expected_class: str,
) -> None:
    import models.cases  # noqa: F401, PLC0415
    import models.normalized_labels  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402
    from models.normalized_labels import (  # noqa: E402
        NormalizedLabelORM,
        SOURCE_TYPE_ANALYST_DISPOSITION,
        case_history_source_id,
    )

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    with TestClient(app) as client:
        _seed_open_case(
            app, case_uuid=case_uuid, shadow_case_id=shadow_case_id, entity_id=entity_id
        )
        r = client.put(
            f"/v1/cases/{case_uuid}/status",
            json={"status": resolved_status, "reason_code": "GATE_ANALYST_FINAL"},
            headers={"X-Auth-Token": "gate-secret-token-labels"},
        )
        assert r.status_code == 200, r.text
        history_row_id = int(r.json()["history_row_id"])

        async def _verify_label() -> None:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as s:
                count = await s.scalar(select(func.count()).select_from(NormalizedLabelORM))
                row = await s.scalar(
                    select(NormalizedLabelORM).where(
                        NormalizedLabelORM.source_id == case_history_source_id(history_row_id),
                    ),
                )
            assert int(count or 0) == 1
            assert row is not None
            assert row.source_type == SOURCE_TYPE_ANALYST_DISPOSITION
            assert row.entity_id == entity_id
            assert row.ground_truth_class == expected_class
            assert "analyst_disposition" in row.tags
            assert resolved_status in row.tags
            assert "reason:GATE_ANALYST_FINAL" in row.tags
            assert row.propagated_to_consortium is False

        asyncio.run(_verify_label())


def test_put_case_status_non_terminal_skips_normalized_label() -> None:
    import models.cases  # noqa: F401, PLC0415
    import models.normalized_labels  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402
    from models.normalized_labels import NormalizedLabelORM  # noqa: E402

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    with TestClient(app) as client:
        _seed_open_case(
            app, case_uuid=case_uuid, shadow_case_id=shadow_case_id, entity_id=entity_id
        )
        r = client.put(
            f"/v1/cases/{case_uuid}/status",
            json={"status": "UNDER_REVIEW", "reason_code": "GATE_ANALYST_REVIEW"},
            headers={"X-Auth-Token": "gate-secret-token-labels"},
        )
        assert r.status_code == 200, r.text

        async def _count_labels() -> int:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as s:
                return int(
                    await s.scalar(select(func.count()).select_from(NormalizedLabelORM)) or 0
                )

        assert asyncio.run(_count_labels()) == 0
