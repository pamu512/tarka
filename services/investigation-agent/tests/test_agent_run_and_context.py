"""Tests for context assembler + AgentRun store + case-brief."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_AGENT_RUN_DB_NAME", "agent_runs_test.sqlite3")
    monkeypatch.delenv("INVESTIGATION_INTERNAL_SECRET", raising=False)
    from investigation_agent import agent_run_store

    agent_run_store.reset_connection_for_tests()
    yield tmp_path
    agent_run_store.reset_connection_for_tests()


def test_assemble_context_snapshot_stable_hashes(data_dir: Path) -> None:
    from investigation_agent.context_assembler import assemble_context_snapshot

    case = {"id": "c1", "status": "OPEN", "entity_id": "e1"}
    s1 = assemble_context_snapshot(
        tenant_id="t1",
        case_id="c1",
        case_payload=case,
        decision_audit={"trace_id": "tr1", "actions": ["FLAG"]},
    )
    s2 = assemble_context_snapshot(
        tenant_id="t1",
        case_id="c1",
        case_payload=case,
        decision_audit={"trace_id": "tr1", "actions": ["FLAG"]},
    )
    assert s1["schema_id"] == "tarka.context_snapshot/v1"
    assert "case" in s1["keys_present"]
    assert "decision_audit" in s1["keys_present"]
    assert s1["freshness"]["graph"] == "missing"
    assert s1["artifacts"][0]["content_hash"] == s2["artifacts"][0]["content_hash"]
    # as_of differs → snapshot_sha256 may differ; artifact hashes must be stable
    assert s1["artifacts"][0]["content_hash"]
    assert s1["artifacts"][1]["content_hash"] == s2["artifacts"][1]["content_hash"]


def test_agent_run_persist_and_tenant_isolation(data_dir: Path) -> None:
    from investigation_agent import agent_run_store
    from investigation_agent.context_assembler import assemble_context_snapshot

    snap = assemble_context_snapshot(tenant_id="ten-a", case_id="c9", case_payload={"id": "c9"})
    rid = agent_run_store.persist_agent_run(
        turn_id="turn-1",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        case_id="c9",
        claims=[{"text": "FLAG on device hub", "source": "tool", "evidence_ids": ["case:c9"]}],
        context_snapshot=snap,
        tool_calls=[{"tool": "get_case", "args": {"case_id": "c9"}, "result": {"id": "c9"}}],
    )
    got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-a")
    assert got is not None
    assert got["turn_id"] == "turn-1"
    assert got["claims"][0]["evidence_ids"] == ["case:c9"]
    assert agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-other") is None
    listed = agent_run_store.list_agent_runs_for_turn(turn_id="turn-1", tenant_id="ten-a")
    assert len(listed) == 1
    assert listed[0]["run_id"] == rid


def test_case_brief_and_agent_run_http(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATION_INTERNAL_SECRET", "brief-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    # Reload settings is hard; TestClient uses module settings — set secret via env before import app
    from investigation_agent.main import app

    with TestClient(app) as client:
        r = client.post(
            "/v1/internal/case-brief",
            json={
                "case": {"id": "case-42", "tenant_id": "t1", "entity_id": "ent-1", "status": "OPEN"}
            },
            headers={"x-internal-secret": "brief-secret"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["llm_used"] is False
        assert "Case brief" in body["brief_markdown"]
        assert body["context_snapshot"]["schema_id"] == "tarka.context_snapshot/v1"

        denied = client.post(
            "/v1/internal/case-brief",
            json={"case": {"id": "case-42", "tenant_id": "t1"}},
            headers={"x-internal-secret": "wrong"},
        )
        assert denied.status_code == 401

        from investigation_agent import agent_run_store
        from investigation_agent.context_assembler import assemble_context_snapshot

        snap = assemble_context_snapshot(
            tenant_id="t1", case_id="case-42", case_payload={"id": "case-42"}
        )
        rid = agent_run_store.persist_agent_run(
            turn_id="turn-http",
            tenant_id="t1",
            analyst_id="a1",
            case_id="case-42",
            context_snapshot=snap,
        )
        g = client.get(f"/v1/agent-runs/{rid}", params={"tenant_id": "t1"})
        assert g.status_code == 200
        assert g.json()["run_id"] == rid
        missing = client.get(f"/v1/agent-runs/{rid}", params={"tenant_id": "other"})
        assert missing.status_code == 404
        listed = client.get("/v1/agent-runs", params={"turn_id": "turn-http", "tenant_id": "t1"})
        assert listed.status_code == 200
        assert listed.json()["items"][0]["run_id"] == rid


def test_chat_returns_agent_run_id_and_get_round_trip(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    monkeypatch.delenv("INVESTIGATION_INTERNAL_SECRET", raising=False)
    from investigation_agent.main import app

    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-1",
                "messages": [{"role": "user", "content": "Summarize this case risk"}],
            },
        )
        assert chat.status_code == 200, chat.text
        payload = chat.json()
        assert payload.get("turn_id")
        rid = payload.get("agent_run_id")
        assert rid, "chat must attach agent_run_id"
        fetched = client.get(f"/v1/agent-runs/{rid}", params={"tenant_id": "t-chat"})
        assert fetched.status_code == 200
        assert fetched.json()["turn_id"] == payload["turn_id"]
        assert fetched.json()["case_id"] == "case-chat-1"

        stream = client.post(
            "/v1/chat/stream",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-2",
                "messages": [{"role": "user", "content": "Stream this"}],
            },
        )
        assert stream.status_code == 200
        assert "agent_run_id" in stream.text


def test_citations_bind_evidence_ids() -> None:
    from investigation_agent.citation_schema import build_standard_citations

    citations, _ = build_standard_citations(
        claims=[
            {
                "text": "Same device spans buyer and seller",
                "source": "tool",
                "evidence_ids": ["case:c1", "okf:ring.cross_role"],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
        case_id="c1",
    )
    assert citations
    ids = {(r["artifact"], r["id"]) for r in citations[0]["resolves_to"]}
    assert ("case", "c1") in ids
    assert ("evidence", "case:c1") in ids
    assert ("okf_concept", "ring.cross_role") in ids


def test_internal_agent_run_post_round_trip(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_INTERNAL_SECRET", "brief-secret")
    from investigation_agent.context_assembler import assemble_context_snapshot
    from investigation_agent.main import app
    from fastapi.testclient import TestClient

    snap = assemble_context_snapshot(
        tenant_id="t1",
        entity_id="ent-1",
        graph_neighborhood={"vertices": [{"id": "ip:9"}]},
    )
    with TestClient(app) as client:
        denied = client.post(
            "/v1/internal/agent-runs",
            json={
                "turn_id": "ingest:tx-1",
                "tenant_id": "t1",
                "analyst_id": "system:shadow",
                "source": "shadow",
                "entity_ids": ["ent-1"],
                "context_snapshot": snap,
                "claims": [{"text": "device hub", "source": "shadow", "evidence_ids": ["graph:x"]}],
            },
            headers={"x-internal-secret": "wrong"},
        )
        assert denied.status_code == 401

        r = client.post(
            "/v1/internal/agent-runs",
            json={
                "turn_id": "ingest:tx-1",
                "tenant_id": "t1",
                "analyst_id": "system:shadow",
                "source": "shadow",
                "entity_ids": ["ent-1"],
                "context_snapshot": snap,
                "claims": [{"text": "device hub", "source": "shadow", "evidence_ids": ["graph:x"]}],
            },
            headers={"x-internal-secret": "brief-secret"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["source"] == "shadow"
        assert body["graph_missing"] is False
        rid = body["run_id"]
        g = client.get(f"/v1/agent-runs/{rid}", params={"tenant_id": "t1"})
        assert g.status_code == 200
        assert g.json()["source"] == "shadow"
        assert g.json()["claims"][0]["evidence_ids"] == ["graph:x"]


def test_graph_missing_and_source_on_get(data_dir: Path) -> None:
    from investigation_agent import agent_run_store
    from investigation_agent.context_assembler import assemble_context_snapshot

    snap = assemble_context_snapshot(tenant_id="ten-a", case_id="c9", case_payload={"id": "c9"})
    rid = agent_run_store.persist_agent_run(
        turn_id="turn-1",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        case_id="c9",
        context_snapshot=snap,
        source="shadow",
    )
    got = agent_run_store.get_agent_run(run_id=rid, tenant_id="ten-a")
    assert got is not None
    assert got["source"] == "shadow"
    assert got["graph_missing"] is True

    snap_g = assemble_context_snapshot(
        tenant_id="ten-a",
        case_id="c9",
        case_payload={"id": "c9"},
        graph_neighborhood={"vertices": [{"id": "device:1"}]},
    )
    rid2 = agent_run_store.persist_agent_run(
        turn_id="turn-2",
        tenant_id="ten-a",
        analyst_id="analyst-1",
        context_snapshot=snap_g,
        source="chat",
    )
    got2 = agent_run_store.get_agent_run(run_id=rid2, tenant_id="ten-a")
    assert got2 is not None
    assert got2["graph_missing"] is False


def test_chat_includes_graph_missing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    from investigation_agent.main import app

    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-1",
                "messages": [{"role": "user", "content": "Summarize this case risk"}],
            },
        )
        assert chat.status_code == 200, chat.text
        assert chat.json()["graph_missing"] is True


def test_chat_persist_failure_is_503(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALLOWED_ANALYSTS", "*")
    from investigation_agent import agent_run_store
    from investigation_agent.main import app

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("sqlite down")

    monkeypatch.setattr(agent_run_store, "persist_agent_run", _boom)
    with TestClient(app) as client:
        chat = client.post(
            "/v1/chat",
            json={
                "tenant_id": "t-chat",
                "analyst_id": "analyst-chat",
                "case_id": "case-chat-1",
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        assert chat.status_code == 503


def test_claims_evidence_binding_is_grounded_not_slap_all() -> None:
    from investigation_agent.context_assembler import claims_with_evidence_ids

    snap = {
        "artifacts": [
            {"evidence_id": "case:c1", "source": "case", "excerpt": "title foo"},
            {"evidence_id": "graph:abc123deadbeef", "source": "graph", "excerpt": "hub device"},
            {"evidence_id": "okf:ring.cross_role", "source": "okf", "excerpt": "cross role"},
        ]
    }
    claims = [
        {"text": "case c1 shows FLAG on shared device", "source": "tool"},
        {"text": "Unrelated claim with no tokens", "source": "tool"},
        {
            "text": "pre-bound",
            "source": "tool",
            "evidence_ids": ["okf:ring.cross_role"],
        },
    ]
    out = claims_with_evidence_ids(claims, snap)
    assert "case:c1" in out[0]["evidence_ids"]
    assert "evidence_ids" not in out[1] or not out[1].get("evidence_ids")
    assert out[2]["evidence_ids"] == ["okf:ring.cross_role"]
