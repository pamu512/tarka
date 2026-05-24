"""Gate: cross-case device linkage surfaces alerts and orange highlights on the timeline API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import tarka_shared.audit_trail  # noqa: F401
from shadow_agent.agent import ShadowAgent
from shadow_agent.main import build_app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

_TEST_SHADOW_API_KEY = "shadow-sidecar-test-api-key"

CLEAN_TX = UUID("11111111-1111-1111-1111-111111111111")
FRAUD_TX = UUID("22222222-2222-2222-2222-222222222222")
SHARED_DEVICE = "device-gate-shared-01"


class _NoopLlm:
    async def chat_json_validated(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        raise RuntimeError("unused in timeline-only tests")


def _auth_headers() -> dict[str, str]:
    return {"X-Shadow-Token": _TEST_SHADOW_API_KEY}


def _audit_payload(
    *,
    tid: UUID,
    amount: float,
    is_fraud: bool,
    case_number: str,
    case_outcome: str,
    device_id: str,
    ip_address: str = "198.51.100.10",
) -> str:
    return json.dumps(
        {
            "transaction_id": str(tid),
            "amount": amount,
            "is_fraud": is_fraud,
            "device_id": device_id,
            "ip_address": ip_address,
            "investigation_case_number": case_number,
            "case_outcome": case_outcome,
        },
        separators=(",", ":"),
    )


@pytest.fixture
def cross_case_app():
    """In-memory shadow DB with a fraud audit 90 days ago sharing device with a clean audit today."""
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_NoopLlm()),  # type: ignore[arg-type]
        database_url="sqlite+aiosqlite:///:memory:",
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        fac: async_sessionmaker[AsyncSession] = client.app.state.async_session_factory
        now = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)
        fraud_ts = now - timedelta(days=90)

        async def _seed() -> None:
            async with fac() as session:
                for cid, name in (
                    (str(FRAUD_TX), "fraud-anchor"),
                    (str(CLEAN_TX), "clean-anchor"),
                ):
                    session.add(
                        Case(
                            id=cid,
                            tenant_id=DEFAULT_TENANT_ID,
                            name=name,
                            dataset_path=None,
                            is_active=False,
                            status=DEFAULT_CASE_STATUS,
                        ),
                    )
                session.add(
                    AuditLog(
                        case_id=str(FRAUD_TX),
                        action_taken=_audit_payload(
                            tid=FRAUD_TX,
                            amount=999.0,
                            is_fraud=True,
                            case_number="123",
                            case_outcome="BLOCKED",
                            device_id=SHARED_DEVICE,
                        ),
                        code_executed=None,
                        agent_notes=None,
                        timestamp=fraud_ts,
                    ),
                )
                session.add(
                    AuditLog(
                        case_id=str(CLEAN_TX),
                        action_taken=_audit_payload(
                            tid=CLEAN_TX,
                            amount=42.0,
                            is_fraud=False,
                            case_number="456",
                            case_outcome="CLEAN",
                            device_id=SHARED_DEVICE,
                        ),
                        code_executed=None,
                        agent_notes=None,
                        timestamp=now,
                    ),
                )
                await session.commit()

        import asyncio

        asyncio.run(_seed())
        yield client


def test_timeline_api_cross_case_alert_and_highlight(cross_case_app: TestClient) -> None:
    r = cross_case_app.get(
        f"/v1/transactions/{CLEAN_TX}/timeline",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entity_id"] == str(CLEAN_TX)
    assert any("High Risk: Device ID matched blocked Case #123" in a for a in data["alerts"]), data[
        "alerts"
    ]
    cross = [e for e in data["events"] if e.get("highlight") == "cross_case"]
    assert len(cross) >= 1
    assert cross[0]["investigation_case_number"] == "123"
    assert cross[0]["matched_via"] == "device_id"


def test_timeline_invalid_entity_returns_400() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_NoopLlm()),  # type: ignore[arg-type]
        database_url="sqlite+aiosqlite:///:memory:",
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        r = client.get("/v1/transactions/not-a-uuid/timeline", headers=_auth_headers())
    assert r.status_code == 400
