"""Gate: TENANT_BINDING_REQUIRED binds Shadow /v1/analyze — shared token is not isolation."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import tarka_shared.audit_trail  # noqa: F401
from agent import ShadowAgent
from history import get_recent_entity_transactions
from main import build_app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
from tarka_shared.database.session import Base

_TEST_SHADOW_API_KEY = "shadow-sidecar-test-api-key"
_ENTITY = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class _StubLlm:
    async def chat_json_validated(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_self_correction_retries: int = 2,
    ) -> dict[str, Any]:
        return {
            "transaction_id": str(_ENTITY),
            "risk_score": 12.5,
            "is_fraud": False,
            "reasoning": ["tenant-bind stub"],
            "confidence_metrics": {"stub": True},
            "ai_reasoning": "tenant-bind stub",
        }


def _body() -> dict[str, Any]:
    return {
        "entity_id": str(_ENTITY),
        "amount": 55.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "ach"},
    }


def _auth(*, tenant: str | None = None) -> dict[str, str]:
    headers = {"X-Shadow-Token": _TEST_SHADOW_API_KEY}
    if tenant:
        headers["X-Tenant-Id"] = tenant
    return headers


def _app() -> Any:
    return build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlm()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )


def test_binding_on_no_tenant_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_TEST_SHADOW_API_KEY: ["tenant_alpha"]}),
    )
    with TestClient(_app()) as client:
        resp = client.post("/v1/analyze", json=_body(), headers=_auth())
    assert resp.status_code == 400
    assert "tenant_id" in str(resp.json().get("detail", "")).lower()


def test_binding_on_missing_map_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.delenv("API_KEY_TENANT_MAP", raising=False)
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/analyze",
            json=_body(),
            headers=_auth(tenant="tenant_alpha"),
        )
    assert resp.status_code == 503
    assert "API_KEY_TENANT_MAP" in str(resp.json().get("detail", ""))


def test_binding_on_unparseable_map_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv("API_KEY_TENANT_MAP", "{not-json")
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/analyze",
            json=_body(),
            headers=_auth(tenant="tenant_alpha"),
        )
    assert resp.status_code == 503


def test_binding_on_does_not_write_default_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_TEST_SHADOW_API_KEY: ["tenant_alpha"]}),
    )
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/analyze",
            json=_body(),
            headers=_auth(tenant="tenant_alpha"),
        )
        fac = client.app.state.async_session_factory

        async def _case_tenant() -> str | None:
            async with fac() as session:
                row = await session.scalar(select(Case).where(Case.id == str(_ENTITY)))
                return None if row is None else row.tenant_id

        written = asyncio.run(_case_tenant())
    assert resp.status_code == 200
    assert written == "tenant_alpha"
    assert written != DEFAULT_TENANT_ID


def test_binding_on_tenant_a_cannot_read_tenant_b_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_TEST_SHADOW_API_KEY: ["tenant_alpha"]}),
    )
    entity_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    async def _seed_and_query() -> tuple[list[float | None], list[float | None]]:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            session.add(
                Case(
                    id=entity_b,
                    tenant_id="tenant_beta",
                    name="other-tenant-history",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            session.add(
                AuditLog(
                    case_id=entity_b,
                    action_taken=json.dumps(
                        {"transaction_id": entity_b, "amount": 999.0, "is_fraud": True},
                        separators=(",", ":"),
                    ),
                    timestamp=datetime(2026, 5, 1, tzinfo=UTC),
                ),
            )
            await session.commit()
            leaked = await get_recent_entity_transactions(
                session, entity_b, 5, tenant_id="tenant_alpha"
            )
            own = await get_recent_entity_transactions(
                session, entity_b, 5, tenant_id="tenant_beta"
            )
        await engine.dispose()
        return [r.amount for r in leaked], [r.amount for r in own]

    leaked, own = asyncio.run(_seed_and_query())
    assert leaked == []
    assert own == [999.0]

    class _CapturePromptLlm:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def chat_json_validated(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            json_self_correction_retries: int = 2,
        ) -> dict[str, Any]:
            system = next(m["content"] for m in messages if m.get("role") == "system")
            self.prompts.append(system)
            return {
                "transaction_id": entity_b,
                "risk_score": 12.5,
                "is_fraud": False,
                "reasoning": ["stub"],
                "confidence_metrics": {"stub": True},
                "ai_reasoning": "stub",
            }

    llm = _CapturePromptLlm()
    app = build_app(shadow_agent=ShadowAgent(llm_client=llm), shadow_api_key=_TEST_SHADOW_API_KEY)
    with TestClient(app) as client:
        fac = client.app.state.async_session_factory

        async def _seed_beta() -> None:
            async with fac() as session:
                session.add(
                    Case(
                        id=entity_b,
                        tenant_id="tenant_beta",
                        name="beta-history",
                        dataset_path=None,
                        is_active=False,
                        status=DEFAULT_CASE_STATUS,
                    ),
                )
                session.add(
                    AuditLog(
                        case_id=entity_b,
                        action_taken=json.dumps(
                            {
                                "transaction_id": entity_b,
                                "amount": 777.0,
                                "is_fraud": True,
                            },
                            separators=(",", ":"),
                        ),
                        timestamp=datetime(2026, 5, 1, tzinfo=UTC) + timedelta(hours=1),
                    ),
                )
                await session.commit()

        asyncio.run(_seed_beta())
        resp = client.post(
            "/v1/analyze",
            json={
                "entity_id": entity_b,
                "amount": 10.0,
                "timestamp": "2026-05-09T12:00:00+00:00",
                "metadata": {},
            },
            headers=_auth(tenant="tenant_alpha"),
        )
    # Existing case belongs to tenant B → fail closed (no B history in prompt).
    assert resp.status_code == 403
    assert not any("777" in p for p in llm.prompts)


def test_binding_off_keeps_single_tenant_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    monkeypatch.delenv("API_KEY_TENANT_MAP", raising=False)
    with TestClient(_app()) as client:
        resp = client.post("/v1/analyze", json=_body(), headers=_auth())
        fac = client.app.state.async_session_factory

        async def _case_tenant() -> str | None:
            async with fac() as session:
                row = await session.scalar(select(Case).where(Case.id == str(_ENTITY)))
                return None if row is None else row.tenant_id

        written = asyncio.run(_case_tenant())
    assert resp.status_code == 200
    assert written == DEFAULT_TENANT_ID
