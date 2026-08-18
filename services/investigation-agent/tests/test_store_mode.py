"""INVESTIGATION_STORE=sqlite|postgres: desk sqlite, fail-closed postgres, live roundtrip."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from investigation_agent import agent_run_store, feedback_store, knowledge_db, review_store
from investigation_agent.store_backend import (
    StoreMisconfigured,
    ensure_store_configured,
    normalize_postgres_url,
    store_config_errors,
    store_mode,
)


def _reset_all() -> None:
    agent_run_store.reset_connection_for_tests()
    feedback_store.reset_connection_for_tests()
    review_store.reset_connection_for_tests()
    knowledge_db.reset_connection_for_tests()


@pytest.fixture()
def isolated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INVESTIGATION_STORE", "sqlite")
    monkeypatch.delenv("INVESTIGATION_DATABASE_URL", raising=False)
    _reset_all()
    yield tmp_path
    _reset_all()


def test_store_mode_defaults_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVESTIGATION_STORE", raising=False)
    assert store_mode() == "sqlite"
    monkeypatch.setenv("INVESTIGATION_STORE", "local-sqlite")
    assert store_mode() == "sqlite"


def test_unknown_store_mode_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_STORE", "mysql")
    with pytest.raises(StoreMisconfigured, match="unknown"):
        store_mode()
    assert store_config_errors()


def test_sqlite_agent_run_and_feedback_roundtrip(isolated_sqlite: Path) -> None:
    rid = agent_run_store.persist_agent_run(
        turn_id="turn-sqlite",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        case_id="c1",
        claims=[{"text": "ok", "source": "tool", "evidence_ids": ["case:c1"]}],
    )
    got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-a")
    assert got is not None
    assert got["turn_id"] == "turn-sqlite"
    assert (isolated_sqlite / "copilot_agent_runs.sqlite3").is_file()

    feedback_store.record_turn(
        turn_id="turn-sqlite",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        case_id="c1",
        playbook_id=None,
        prompt_version="3.2.0",
        reply_preview="hello",
        tool_count=1,
    )
    fid = feedback_store.save_feedback(
        turn_id="turn-sqlite",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        rating=1,
        note="good",
        claim_indices=[0],
    )
    assert fid > 0
    assert feedback_store.lookup_turn("turn-sqlite")["tenant_id"] == "ten-a"


def test_postgres_mode_without_url_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INVESTIGATION_STORE", "postgres")
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("INVESTIGATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _reset_all()
    errs = store_config_errors()
    assert errs
    assert "INVESTIGATION_DATABASE_URL" in errs[0]
    with pytest.raises(StoreMisconfigured):
        ensure_store_configured()
    with pytest.raises(StoreMisconfigured):
        agent_run_store.persist_agent_run(
            turn_id="nope",
            tenant_id="t",
            analyst_id="a",
        )
    _reset_all()


def test_ready_503_when_store_misconfigured() -> None:
    from investigation_agent.main import app

    with TestClient(app) as client:
        with patch(
            "investigation_agent.main.store_config_errors",
            return_value=["INVESTIGATION_STORE=postgres requires a URL"],
        ):
            response = client.get("/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "store_misconfigured" in body["errors"]


def test_normalize_asyncpg_url() -> None:
    assert (
        normalize_postgres_url("postgresql+asyncpg://fraud:pw@db:5432/fraud")
        == "postgresql://fraud:pw@db:5432/fraud"
    )


@pytest.fixture(scope="module")
def postgres_url() -> str:
    url = None
    for key in ("INVESTIGATION_TEST_DATABASE_URL", "DATABASE_URL"):
        raw = (os.environ.get(key) or "").strip()
        if raw and raw.startswith("postgres"):
            url = normalize_postgres_url(raw)
            break
    if url:
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("no INVESTIGATION_TEST_DATABASE_URL/DATABASE_URL and no testcontainers")
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield normalize_postgres_url(container.get_connection_url())
    finally:
        container.stop()


def test_postgres_run_and_feedback_roundtrip(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INVESTIGATION_STORE", "postgres")
    monkeypatch.setenv("INVESTIGATION_DATABASE_URL", postgres_url)
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    _reset_all()
    try:
        rid = agent_run_store.persist_agent_run(
            turn_id="turn-pg",
            tenant_id="ten-pg",
            analyst_id="analyst-pg",
            case_id="c-pg",
            claims=[{"text": "pg row", "source": "tool", "evidence_ids": ["case:c-pg"]}],
        )
        got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-pg")
        assert got is not None
        assert got["turn_id"] == "turn-pg"
        assert got["claims"][0]["text"] == "pg row"
        assert agent_run_store.get_agent_run(run_id=rid, tenant_id="other") is None

        feedback_store.record_turn(
            turn_id="turn-pg",
            tenant_id="ten-pg",
            analyst_id="analyst-pg",
            case_id="c-pg",
            playbook_id=None,
            prompt_version="3.2.0",
            reply_preview="pg hello",
            tool_count=2,
        )
        fid = feedback_store.save_feedback(
            turn_id="turn-pg",
            tenant_id="ten-pg",
            analyst_id="analyst-pg",
            rating=1,
            note="pg good",
            claim_indices=[0],
        )
        assert fid > 0
        recent = feedback_store.list_recent_feedback("ten-pg", 10)
        assert any(r["turn_id"] == "turn-pg" and r["rating"] == 1 for r in recent)

        rev_id = review_store.save_review(
            turn_id="turn-pg",
            tenant_id="ten-pg",
            analyst_id="reviewer-1",
            status="approved",
            note="ok",
        )
        assert rev_id > 0
        latest = review_store.latest_review("turn-pg", "ten-pg")
        assert latest is not None
        assert latest["status"] == "approved"

        doc_id = knowledge_db.ingest_document_sync(
            "ten-pg", "analyst-pg", "memo", "shared postgres rag chunk"
        )
        hits = knowledge_db.search_keyword_only("ten-pg", "analyst-pg", "postgres rag", limit=5)
        assert any(doc_id == h["doc_id"] for h in hits)
        ok, detail = knowledge_db.health_check()
        assert ok, detail
    finally:
        _reset_all()
