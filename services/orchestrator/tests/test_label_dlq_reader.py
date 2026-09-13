"""Gate: ``tarka_label_dlq`` gets production readers (list + counts + purge) (A3)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI  # noqa: E402

from main import create_app  # noqa: E402
from models.label_dlq import TarkaLabelDlqDAO, TarkaLabelDlqORM  # noqa: E402


def _build_reader_app(monkeypatch_token: str) -> FastAPI:
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    return app


async def _seed(factory, n: int = 3) -> None:
    async with factory() as s:
        for i in range(n):
            await TarkaLabelDlqDAO.record_malformed_label(
                s,
                normalized_label_id=uuid.uuid4(),
                entity_id=f"entity-{i}",
                ground_truth_class="FRAUD",
                rejection_reason=f"reason-{i}",
                payload={"i": i},
                source="label_propagator",
            )
        await s.commit()


def test_dao_list_and_counts(tmp_path: Path) -> None:
    import models.cases  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401

    app = _build_reader_app("k")
    with TestClient(app) as client:
        asyncio.run(_seed(app.state.audit_session_factory, 3))

        async def _call():
            factory = app.state.audit_session_factory
            async with factory() as s:
                rows = await TarkaLabelDlqDAO.list_recent(s, limit=2)
                counts = await TarkaLabelDlqDAO.count_by_reason(s)
            return rows, counts

        rows, counts = asyncio.run(_call())
        assert len(rows) == 2
        assert sum(counts.values()) == 3
        assert rows[0].rejection_reason.startswith("reason-")


def test_internal_label_dlq_endpoint_requires_secret() -> None:
    import models.cases  # noqa: F401

    app = _build_reader_app("k")
    with TestClient(app) as client:
        r = client.get("/v1/internal/label-dlq/recent")
        assert r.status_code == 401, r.text


def test_internal_label_dlq_endpoint_lists_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    import models.cases  # noqa: F401

    monkeypatch.setenv("ORCHESTRATOR_INTERNAL_SECRET", "sec-a3")
    app = _build_reader_app("k")
    with TestClient(app) as client:
        asyncio.run(_seed(app.state.audit_session_factory, 3))
        r = client.get(
            "/v1/internal/label-dlq/recent",
            headers={"x-internal-secret": "sec-a3"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_written"] == 3
        assert len(body["items"]) == 3
        assert body["items"][0]["entity_id"].startswith("entity-")
