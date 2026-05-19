"""Gate (Prompt 113): Shadow hook calls Case Transition API when confidence > 0.95 → RESOLVED_AUTO."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


async def _run_with_client(
    transport: httpx.ASGITransport,
    fn: Callable[[httpx.AsyncClient], Awaitable[None]],
) -> None:
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await fn(client)


def test_mock_ai_high_confidence_autoresolves_to_resolved_auto() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from shadow.hooks.resolve_case import (  # noqa: E402
        CONFIDENCE_THRESHOLD,
        maybe_autoresolve_lifecycle_case,
    )
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
                    name="shadow-anchor-113",
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
                    user_link_key="u_gate_shadow_auto",
                    entity_id=str(uuid.uuid4()),
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            await s.commit()

    async def _call_hook(client: httpx.AsyncClient) -> None:
        mock_ai_confidence = min(1.0, CONFIDENCE_THRESHOLD + 0.04)
        out = await maybe_autoresolve_lifecycle_case(
            orchestrator_base_url="http://testserver",
            case_id=case_uuid,
            confidence=mock_ai_confidence,
            auth_token="shadow-agent-gate-113",
            client=client,
        )

        assert out.called_api is True
        assert out.skipped_reason is None
        assert out.http_status == 200
        assert out.response_json is not None
        assert out.response_json.get("status") == CaseStatus.RESOLVED_AUTO.value

        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            row = await s.scalar(select(CaseORM).where(CaseORM.case_id == case_uuid))
        assert row is not None
        assert row.status == CaseStatus.RESOLVED_AUTO.value

    with TestClient(app):
        asyncio.run(_seed())
        transport = httpx.ASGITransport(app=app)
        asyncio.run(
            _run_with_client(transport, _call_hook),
        )


def test_autoresolve_skipped_when_confidence_at_threshold() -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from shadow.hooks.resolve_case import (
        CONFIDENCE_THRESHOLD,
        maybe_autoresolve_lifecycle_case,
    )  # noqa: E402
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
                    name="shadow-anchor-113b",
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
                    user_link_key="u_gate_shadow_auto_b",
                    entity_id=str(uuid.uuid4()),
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            await s.commit()

    async def _call_hook(client: httpx.AsyncClient) -> None:
        out = await maybe_autoresolve_lifecycle_case(
            orchestrator_base_url="http://testserver",
            case_id=case_uuid,
            confidence=CONFIDENCE_THRESHOLD,
            auth_token="tok",
            client=client,
        )
        assert out.called_api is False
        assert out.skipped_reason == "confidence_not_above_threshold"

        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            row = await s.scalar(select(CaseORM).where(CaseORM.case_id == case_uuid))
        assert row is not None
        assert row.status == CaseStatus.OPEN.value

    with TestClient(app):
        asyncio.run(_seed())
        transport = httpx.ASGITransport(app=app)
        asyncio.run(_run_with_client(transport, _call_hook))
