"""Gate (Prompt 122): chargeback ingest resolves ``session_id`` and materializes a ``Dispute``-tagged lifecycle case."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _RuleOnlyClient:
    def __init__(self, evaluate_json: dict[str, object]) -> None:
        self._evaluate_json = evaluate_json
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> _RuleOnlyClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        self.post_calls.append((url, json or {}))
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        raise AssertionError(f"unexpected post url: {url!r}")


def test_chargeback_ingest_links_session_and_tags_dispute(monkeypatch: pytest.MonkeyPatch) -> None:
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    from orchestrator.audit_case_worker import run_audit_poll_once
    from orchestrator.main import create_app
    from orchestrator.models.cases import CaseORM
    from sqlalchemy import select
    from tarka_shared.audit_trail import AuditLog, Case
    from tarka_shared.case_status import DEFAULT_CASE_STATUS
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

    orig = uuid.uuid4()
    orig_s = str(orig)
    payment_snapshot = {
        "amount": 80.0,
        "transaction_id": orig_s,
        "metadata": {"session_id": "sess-checkout-orig-122", "channel": "card"},
        "country": "US",
    }

    rule_engine_body: dict[str, object] = {
        "actions": ["FLAG"],
        "transaction_id": orig_s,
        "evaluation_trace": [],
        "blocking_rule_id": None,
        "risk_score": 55.0,
    }
    dummy = _RuleOnlyClient(rule_engine_body)
    monkeypatch.setattr("orchestrator.transaction_ingest.httpx.AsyncClient", lambda *a, **k: dummy)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        audit_background_poll=False,
    )

    async def _seed(fac: object) -> None:
        async with fac() as session:  # type: ignore[misc]
            async with session.begin():
                session.add(
                    Case(
                        id=orig_s,
                        tenant_id=DEFAULT_TENANT_ID,
                        name="payment-anchor",
                        dataset_path=None,
                        is_active=False,
                        status=DEFAULT_CASE_STATUS,
                    ),
                )
                session.add(
                    AuditLog(
                        case_id=orig_s,
                        action_taken=json.dumps(payment_snapshot, separators=(",", ":")),
                        agent_notes=None,
                        code_executed=None,
                    ),
                )

    with TestClient(app) as client:
        fac = client.app.state.audit_session_factory
        assert fac is not None
        asyncio.run(_seed(fac))
        r = client.post(
            "/v1/ingest/chargeback",
            json={
                "original_entity_id": orig_s,
                "amount": 80.0,
                "metadata": {"reason_code": "duplicate_processing"},
            },
        )
        assert r.status_code == 200, r.text
        dispute_tid = r.json()["transaction_id"]
        assert dispute_tid != orig_s
        ev_body = dummy.post_calls[0][1]
        assert ev_body["metadata"]["session_id"] == "sess-checkout-orig-122"
        assert ev_body["metadata"]["linked_session_id"] == "sess-checkout-orig-122"

        asyncio.run(run_audit_poll_once(fac))

        async def _load_case() -> CaseORM | None:
            async with fac() as session:  # type: ignore[misc]
                return await session.scalar(select(CaseORM).where(CaseORM.entity_id == dispute_tid).limit(1))

        row = asyncio.run(_load_case())
    assert row is not None
    assert row.linked_session_id == "sess-checkout-orig-122"
    assert row.case_labels == ["Dispute"]
