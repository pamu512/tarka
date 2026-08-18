"""Decision context graph — store + HTTP (Wave 1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "decisions.sqlite"
    monkeypatch.setenv("DECISION_GRAPH_DB_PATH", str(path))
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("DECISION_GRAPH_ENABLED", "1")
    return path


def test_record_and_get_decision(db_path: Path) -> None:
    from graph_service.decision_context_store import get_decision, record_decision

    did = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="tx-1 allow/deny",
        outcome="review",
        reasoning="rule velocity_spike fired",
        rule_ids=["velocity_spike"],
        entity_external_ids=["acct-1"],
        evidence_ids=["ev-1"],
        audit_log_id="al-1",
        confidence=0.81,
    )
    assert did.startswith("dec_")
    row = get_decision("t1", did)
    assert row is not None
    assert row["outcome"] == "review"
    assert row["rule_ids"] == ["velocity_spike"]
    assert row["entity_external_ids"] == ["acct-1"]
    assert row["invalidated_at"] is None


def test_causal_chain_and_impact(db_path: Path) -> None:
    from graph_service.decision_context_store import (
        add_edge,
        get_chain,
        get_impact,
        record_decision,
    )

    a = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="evaluate",
        outcome="review",
        reasoning="rules",
    )
    b = record_decision(
        tenant_id="t1",
        kind="agent_advise",
        category="case_status_propose",
        scenario="propose escalate",
        outcome="escalated",
        reasoning="graph ring",
        agent_run_id="run-1",
    )
    c = record_decision(
        tenant_id="t1",
        kind="human_disposition",
        category="case_status",
        scenario="confirm escalate",
        outcome="escalated",
        reasoning="analyst confirms",
        case_id="case-1",
    )
    add_edge("t1", a, b, "INFLUENCED")
    add_edge("t1", b, c, "CAUSED")

    chain = get_chain("t1", c, max_depth=5)
    assert [n["external_id"] for n in chain["nodes"]] == [c, b, a]
    assert len(chain["edges"]) == 2

    impact = get_impact("t1", a, max_depth=5)
    assert {n["external_id"] for n in impact["nodes"]} == {a, b, c}


def test_invalidate_and_search(db_path: Path) -> None:
    from graph_service.decision_context_store import (
        get_decision,
        invalidate_decision,
        record_decision,
        search_decisions,
    )

    did = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="Choose vendor path",
        outcome="deny",
        reasoning="sanctions hit",
        entity_external_ids=["acct-9"],
    )
    invalidate_decision("t1", did, reason="false positive")
    row = get_decision("t1", did)
    assert row is not None
    assert row["invalidated_at"]
    assert row["invalidation_reason"] == "false positive"

    hits = search_decisions(
        tenant_id="t1",
        entity_external_id="acct-9",
        outcome="deny",
        q="sanctions",
        limit=10,
    )
    assert len(hits) == 1
    assert hits[0]["external_id"] == did


def test_http_decision_endpoints(db_path: Path) -> None:
    # Fresh import path for env-bound store
    os.environ["DECISION_GRAPH_DB_PATH"] = str(db_path)
    from graph_service.main import app

    with TestClient(app) as client:
        r = client.post(
            "/v1/decisions",
            json={
                "tenant_id": "t1",
                "kind": "evaluate",
                "category": "transaction_evaluate",
                "scenario": "http evaluate",
                "outcome": "allow",
                "reasoning": "no rules",
                "entity_external_ids": ["e1"],
            },
        )
        assert r.status_code == 200, r.text
        did = r.json()["external_id"]

        r2 = client.get(f"/v1/decisions/{did}", params={"tenant_id": "t1"})
        assert r2.status_code == 200
        assert r2.json()["outcome"] == "allow"

        child = client.post(
            "/v1/decisions",
            json={
                "tenant_id": "t1",
                "kind": "agent_advise",
                "category": "case_brief",
                "scenario": "advise",
                "outcome": "review",
                "reasoning": "copilot",
                "edges": [{"from_external_id": did, "relationship": "INFLUENCED"}],
            },
        )
        assert child.status_code == 200
        cid = child.json()["external_id"]

        chain = client.get(f"/v1/decisions/{cid}/chain", params={"tenant_id": "t1"})
        assert chain.status_code == 200
        assert len(chain.json()["nodes"]) >= 2

        impact = client.get(f"/v1/decisions/{did}/impact", params={"tenant_id": "t1"})
        assert impact.status_code == 200
        assert len(impact.json()["nodes"]) >= 2

        search = client.get(
            "/v1/decisions/search",
            params={"tenant_id": "t1", "q": "http", "limit": 5},
        )
        assert search.status_code == 200
        assert any(x["external_id"] == did for x in search.json()["decisions"])

        prec = client.get(
            "/v1/decisions/precedents",
            params={
                "tenant_id": "t1",
                "from_external_id": did,
                "limit": 5,
            },
        )
        assert prec.status_code == 200
        assert prec.json().get("ranking") == "overlap_v1"

        inv = client.post(
            f"/v1/decisions/{did}/invalidate",
            json={"tenant_id": "t1", "reason": "replay", "supersede_to": cid},
        )
        assert inv.status_code == 200
        assert inv.json()["invalidated_at"]


def test_accountability_snapshot(db_path: Path) -> None:
    from graph_service.decision_context_store import (
        accountability_snapshot,
        add_edge,
        record_decision,
    )

    a = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="x",
        scenario="s1",
        outcome="review",
        reasoning="r",
        trace_id="tr-1",
    )
    b = record_decision(
        tenant_id="t1",
        kind="agent_advise",
        category="y",
        scenario="s2",
        outcome="advise",
        reasoning="r",
        case_id="case-1",
    )
    add_edge("t1", a, b, "INFLUENCED")
    snap = accountability_snapshot("t1", case_id="case-1", trace_id="tr-1")
    assert snap["schema_id"] == "tarka.decision_context/v1"
    assert len(snap["decisions"]) >= 2
    assert any(e["to_external_id"] == b for e in snap["edges"])


def test_find_latest_and_neighbors(db_path: Path) -> None:
    from graph_service.decision_context_store import (
        find_latest,
        get_neighbor_summary,
        invalidate_decision,
        record_decision,
    )

    a = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="first",
        outcome="review",
        reasoning="r1",
        trace_id="tr-1",
    )
    b = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="second",
        outcome="deny",
        reasoning="r2",
        trace_id="tr-1",
    )
    latest = find_latest("t1", kind="evaluate", trace_id="tr-1")
    assert latest is not None
    assert latest["external_id"] == b
    neighbors = get_neighbor_summary("t1", b)
    assert isinstance(neighbors["inbound"], list)
    invalidate_decision("t1", a, "superseded", supersede_to=b)
    row = find_latest("t1", kind="evaluate", trace_id="tr-1", exclude_external_id="skip")
    assert row["external_id"] == b


def test_rank_precedents_scores_entity_category_outcome_rules(db_path: Path) -> None:
    from graph_service.decision_context_store import rank_precedents, record_decision

    record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="unrelated",
        outcome="allow",
        reasoning="other account",
        entity_external_ids=["acct-zzz"],
        rule_ids=["other_rule"],
    )
    best = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="same ring",
        outcome="review",
        reasoning="velocity on shared device",
        entity_external_ids=["acct-1", "dev-9"],
        rule_ids=["velocity_spike", "device_reuse"],
    )
    mid = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="same entity other outcome",
        outcome="allow",
        reasoning="cleared",
        entity_external_ids=["acct-1"],
        rule_ids=["velocity_spike"],
    )
    ranked = rank_precedents(
        tenant_id="t1",
        category="transaction_evaluate",
        outcome="review",
        entity_external_ids=["acct-1", "dev-9"],
        rule_ids=["velocity_spike", "device_reuse"],
        kind="evaluate",
        limit=5,
    )
    ids = [h["external_id"] for h in ranked]
    assert ids[0] == best
    assert mid in ids
    assert ranked[0]["score"] > ranked[1]["score"]
    assert ranked[0]["score_breakdown"]["entity"] > 0
    assert ranked[0]["score_breakdown"]["rules"] > 0
    assert (
        "unrelated" not in {h["scenario"] for h in ranked}
        or ranked[-1]["score"] < ranked[0]["score"]
    )


def test_rank_precedents_skips_invalidated_and_self(db_path: Path) -> None:
    from graph_service.decision_context_store import (
        invalidate_decision,
        rank_precedents,
        record_decision,
    )

    probe = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="probe",
        outcome="deny",
        reasoning="probe",
        entity_external_ids=["acct-1"],
        rule_ids=["sanctions"],
    )
    dead = record_decision(
        tenant_id="t1",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="old false positive",
        outcome="deny",
        reasoning="stale",
        entity_external_ids=["acct-1"],
        rule_ids=["sanctions"],
    )
    invalidate_decision("t1", dead, "false positive")
    ranked = rank_precedents(
        tenant_id="t1",
        from_external_id=probe,
        limit=10,
    )
    ids = [h["external_id"] for h in ranked]
    assert probe not in ids
    assert dead not in ids
