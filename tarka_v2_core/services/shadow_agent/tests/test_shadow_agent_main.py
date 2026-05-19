"""FastAPI sidecar: ``POST /v1/analyze`` and hardened surface (no OpenAPI UI)."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from uuid import UUID

import pytest
import tarka_shared.audit_trail  # noqa: F401
from shadow_agent.agent import ShadowAgent
from shadow_agent.main import build_app
from shadow_agent.schemas import ShadowDecision
from sqlalchemy import func, select
from starlette.testclient import TestClient
from tarka_shared.audit_trail import AuditLog

# Injected only via ``build_app(shadow_api_key=...)`` — never committed as a production secret.
_TEST_SHADOW_API_KEY = "shadow-sidecar-test-api-key"

_ENTITY_LINE = re.compile(
    r"entity_id \(canonical transaction id for this case\):\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


class _StubLlmEchoEntity:
    """Parses ``entity_id`` from the forensic system prompt and returns a valid ``ShadowDecision`` dict."""

    async def chat_json_validated(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_self_correction_retries: int = 2,
    ) -> dict[str, Any]:
        system = next(m["content"] for m in messages if m.get("role") == "system")
        match = _ENTITY_LINE.search(system)
        if not match:
            raise RuntimeError("stub expected entity_id line in system prompt")
        uid = match.group(1)
        linked = bool(
            re.search(
                r"linked_to_blocked_node[\"']?\s*:\s*(?:true|True)\b",
                system,
            ),
        )
        return {
            "transaction_id": uid,
            "risk_score": 88.0 if linked else 12.5,
            "is_fraud": bool(linked),
            "reasoning": (
                ["Linked to Blocked Node", "device_id overlaps blocked account"]
                if linked
                else ["stub gate"]
            ),
            "confidence_metrics": {"stub": True},
            "ai_reasoning": (
                "Linked to Blocked Node: this device_id was previously linked to a blocked account."
                if linked
                else "stub gate narrative"
            ),
        }


def _auth_headers() -> dict[str, str]:
    return {"X-Shadow-Token": _TEST_SHADOW_API_KEY}


def test_analyze_envelope_graph_context_linked_blocked_phrase_in_ai_reasoning() -> None:
    """Gate: graph_context marks shared hardware with blocked account → stub LLM cites Linked to Blocked Node."""
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    tx_id = UUID("f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0")
    body = {
        "transaction": {
            "entity_id": str(tx_id),
            "amount": 99.0,
            "timestamp": "2026-05-09T12:00:00+00:00",
            "metadata": {"user_id": "new_user", "device_id": "dev_shared"},
        },
        "graph_context": {
            "device_hardware_graph": {
                "device_id": "dev_shared",
                "linked_to_blocked_node": True,
                "blocked_user_count_on_device": 1,
            },
        },
    }
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json=body, headers=_auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert "Linked to Blocked Node" in data.get("ai_reasoning", "")


def test_post_v1_analyze_returns_200_and_shadow_decision() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    tx_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    body = {
        "entity_id": str(tx_id),
        "amount": 55.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "ach"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json=body, headers=_auth_headers())
        fac = client.app.state.async_session_factory

        async def _audit_rows() -> int:
            async with fac() as session:
                return int(
                    (
                        await session.execute(select(func.count()).select_from(AuditLog))
                    ).scalar_one(),
                )

        row_count = asyncio.run(_audit_rows())
    assert response.status_code == 200
    data = response.json()
    assert "_debug" in data
    assert "audit_log" in data["_debug"]
    assert "AuditLog" in data["_debug"]["audit_log"]
    assert data["_debug"].get("audit_log_id") is not None
    assert row_count >= 1

    snap = data["_debug"]["audit_log_snapshot"]
    assert snap["transaction_id_correlation"] == str(tx_id)
    assert str(tx_id) in snap["raw_llm_prompt_excerpt"]
    assert snap["is_fraud"] is False
    parsed = ShadowDecision.model_validate({k: v for k, v in data.items() if k != "_debug"})
    assert parsed.transaction_id == tx_id
    assert parsed.risk_score == 12.5
    assert str(tx_id) in response.text


def test_chaos_latency_injects_sleep_before_analyze(monkeypatch: pytest.MonkeyPatch) -> None:
    """``CHAOS_LATENCY`` delays ``POST /v1/analyze`` but must not affect ``GET /health/db``."""
    monkeypatch.setenv("CHAOS_LATENCY", "150")
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    tx_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    body = {
        "entity_id": str(tx_id),
        "amount": 55.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "ach"},
    }
    t0 = time.perf_counter()
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json=body, headers=_auth_headers())
    assert time.perf_counter() - t0 >= 0.12
    assert response.status_code == 200

    t1 = time.perf_counter()
    with TestClient(app) as client:
        response2 = client.get("/health/db", headers=_auth_headers())
    assert time.perf_counter() - t1 < 0.09
    assert response2.status_code == 200


def test_health_db_returns_ok() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        response = client.get("/health/db", headers=_auth_headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_and_docs_disabled() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_analyze_missing_amount_returns_legacy_422_and_rejected_ingestion_audit() -> None:
    """Invalid ``TransactionSchema`` body: legacy Tarka ``error`` envelope + ``REJECTED_INGESTION`` audit row."""
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    tx_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    body: dict[str, object] = {
        "entity_id": str(tx_id),
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "ach"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json=body, headers=_auth_headers())
        fac = client.app.state.async_session_factory

        async def _last_rejection() -> AuditLog | None:
            async with fac() as session:
                res = await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action_taken == "REJECTED_INGESTION")
                    .order_by(AuditLog.id.desc())
                    .limit(1),
                )
                return res.scalars().first()

        row = asyncio.run(_last_rejection())

    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    err = data["error"]
    assert err["code"] == "request_validation_error"
    assert err["message"] == "Transaction ingestion payload failed validation"
    assert err["status_code"] == 422
    assert err["retryable"] is False
    assert isinstance(err["support_id"], str) and len(err["support_id"]) == 12
    assert "errors" in err["details"]
    assert row is not None
    assert row.case_id == str(tx_id)
    assert "REJECTED" in row.action_taken
    assert row.action_taken == "REJECTED_INGESTION"


def test_build_app_without_shadow_api_key_env_raises_on_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SHADOW_API_KEY", raising=False)
    app = build_app(shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()))
    with pytest.raises(RuntimeError, match="SHADOW_API_KEY"):
        with TestClient(app):
            pass


def test_health_db_without_x_shadow_token_returns_401() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        response = client.get("/health/db")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_analyze_without_x_shadow_token_returns_401() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    tx_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    body = {
        "entity_id": str(tx_id),
        "amount": 1.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        response = client.post("/v1/analyze", json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_post_check_review_integrity_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_check(listing_id: str, _drv: object) -> dict[str, Any]:
        return {
            "listing_id": listing_id,
            "reviewer_count": 2,
            "review_ring_likely": False,
            "risk_summary": "stub",
        }

    class _FakeDriver:
        async def close(self) -> None:
            return None

    monkeypatch.setattr("shadow_agent.main.check_review_integrity", _fake_check)
    monkeypatch.setattr("shadow_agent.main.neo4j_driver_from_env", lambda: _FakeDriver())

    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/tools/check-review-integrity",
            json={"listing_id": "L-99"},
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["listing_id"] == "L-99"
    assert data["reviewer_count"] == 2


def test_post_check_review_integrity_requires_listing_id() -> None:
    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlmEchoEntity()),
        shadow_api_key=_TEST_SHADOW_API_KEY,
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/tools/check-review-integrity",
            json={},
            headers=_auth_headers(),
        )
    assert response.status_code == 422
