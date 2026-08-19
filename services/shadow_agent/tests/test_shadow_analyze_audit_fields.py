"""Gate: Shadow analyze AuditLog persists tenant + model backend/URL; not Observe shadow."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
import tarka_shared.audit_trail  # noqa: F401
from agent import ShadowAgent, safe_model_endpoint, shadow_llm_audit_fields
from llm_client import OllamaLLMClient
from main import build_app
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient
from tarka_shared.audit_trail import AuditLog
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

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
            "reasoning": ["audit-fields stub"],
            "confidence_metrics": {"stub": True},
            "ai_reasoning": "audit-fields stub",
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


def _persisted_action(client: TestClient) -> dict[str, Any]:
    fac = client.app.state.async_session_factory

    async def _row() -> AuditLog | None:
        async with fac() as session:
            return (
                (await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)))
                .scalars()
                .first()
            )

    row = asyncio.run(_row())
    assert row is not None
    assert row.code_executed
    assert row.agent_notes
    payload = json.loads(row.action_taken)
    assert isinstance(payload, dict)
    return payload


def test_safe_model_endpoint_strips_userinfo_query_and_fragment() -> None:
    assert (
        safe_model_endpoint("https://user:s3cret@vllm.internal:8000/v1?api_key=leak#x")
        == "https://vllm.internal:8000/v1"
    )
    assert safe_model_endpoint("http://localhost:11434") == "http://localhost:11434"
    assert safe_model_endpoint("ollama-host:11434?token=no") == "ollama-host:11434"


def test_shadow_llm_audit_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "vllm")
    monkeypatch.setenv("SHADOW_LLM_BASE_URL", "http://user:pw@vllm:8000/v1?key=secret")
    fields = shadow_llm_audit_fields(None)
    assert fields["llm_backend"] == "vllm"
    assert fields["model_url"] == "http://vllm:8000/v1"
    assert "secret" not in fields["model_url"]
    assert "pw" not in fields["model_url"]


def test_analyze_audit_row_has_tenant_backend_url_not_observe_shadow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_TEST_SHADOW_API_KEY: ["tenant_alpha"]}),
    )
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "ollama")
    monkeypatch.setenv("SHADOW_LLM_BASE_URL", "http://127.0.0.1:11434")
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/analyze",
            json=_body(),
            headers=_auth(tenant="tenant_alpha"),
        )
        action = _persisted_action(client)
    assert resp.status_code == 200
    assert action["tenant_id"] == "tenant_alpha"
    assert action["tenant_id"] != DEFAULT_TENANT_ID
    assert action["llm_backend"] == "ollama"
    assert action["model_url"]
    assert "11434" in action["model_url"] or "127.0.0.1" in action["model_url"]
    assert action.get("shadow") is not True
    assert "shadow" not in action
    snap = resp.json()["_debug"]["audit_log_snapshot"]
    assert snap["tenant_id"] == "tenant_alpha"
    assert snap["llm_backend"] == "ollama"
    assert snap["model_url"]
    assert snap.get("shadow") is not True
    assert "shadow" not in snap


def test_binding_off_analyze_audit_row_uses_default_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "self-hosted")
    monkeypatch.setenv("SHADOW_LLM_BASE_URL", "http://vllm.internal:8000/v1")
    with TestClient(_app()) as client:
        resp = client.post("/v1/analyze", json=_body(), headers=_auth())
        action = _persisted_action(client)
    assert resp.status_code == 200
    assert action["tenant_id"] == DEFAULT_TENANT_ID
    assert action["llm_backend"] == "self-hosted"
    assert action["model_url"] == "http://vllm.internal:8000/v1"
    assert "shadow" not in action


def test_timeout_fallback_still_persists_tenant_and_model_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    def _raise_read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout", request=request)

    transport = httpx.MockTransport(_raise_read_timeout)
    llm = OllamaLLMClient(
        client=httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:11434",
            timeout=httpx.Timeout(0.001),
        ),
        max_retries=1,
        retry_wait_initial_sec=0.0,
        retry_wait_max_sec=0.0,
    )
    app = build_app(shadow_agent=ShadowAgent(llm_client=llm), shadow_api_key=_TEST_SHADOW_API_KEY)
    with TestClient(app) as client:
        resp = client.post("/v1/analyze", json=_body(), headers=_auth())
        action = _persisted_action(client)
    assert resp.status_code == 200
    assert resp.json()["reasoning"] == ["TIMEOUT_FALLBACK"]
    assert action["tenant_id"] == DEFAULT_TENANT_ID
    assert action["llm_backend"] == "ollama"
    assert "11434" in action["model_url"]
    assert "shadow" not in action


def test_analyze_persist_failure_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit persist failure stays fail-closed (503). Bootstrap commit is not the row."""
    from tarka_shared.audit_errors import AuditPersistenceError

    async def _fail(
        self: ShadowAgent,
        tx: object,
        session: object,
        **_kw: object,
    ) -> tuple[object, object]:
        raise AuditPersistenceError.persist_failed(
            entity_id=str(getattr(tx, "entity_id", "")),
            component="shadow",
            http_status=503,
        )

    monkeypatch.setattr(ShadowAgent, "evaluate", _fail)
    with TestClient(_app()) as client:
        resp = client.post("/v1/analyze", json=_body(), headers=_auth())
    assert resp.status_code == 503
    detail = resp.json().get("detail") or {}
    assert detail.get("error") == "audit_persist_failed"


def test_evaluate_commit_failure_raises_audit_persistence_error() -> None:
    from datetime import UTC, datetime

    from ingestor.schemas import TransactionSchema
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from tarka_shared.audit_errors import AuditPersistenceError
    from tarka_shared.database.session import Base

    tx = TransactionSchema(
        entity_id=_ENTITY,
        amount=10.0,
        timestamp=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
        metadata={},
    )
    agent = ShadowAgent(llm_client=_StubLlm())

    async def _run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:

            async def _boom() -> None:
                raise OperationalError("INSERT", {}, Exception("audit disk full"))

            session.commit = _boom  # type: ignore[method-assign]
            with pytest.raises(AuditPersistenceError) as caught:
                await agent.evaluate(tx, session)
            assert caught.value.http_status == 503
            assert caught.value.error_code == "audit_persist_failed"
        await engine.dispose()

    asyncio.run(_run())
