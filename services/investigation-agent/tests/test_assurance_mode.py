"""Strict assurance, derived facts, and review store."""

from investigation_agent import review_store
from investigation_agent.copilot_hardening import (
    deterministic_claim_support,
    extract_derived_facts,
    format_assurance_refusal,
    strict_assurance_violations,
)


def test_extract_derived_facts_from_tool_payload():
    tool_calls = [
        {
            "tool": "get_case",
            "args": {"case_id": "c1"},
            "result": {"id": "c1", "status": "open", "priority": "high", "nested": {"x": 1}},
        },
        {"tool": "broken", "args": {}, "result": {"error": "nope"}},
    ]
    facts = extract_derived_facts(tool_calls, max_items=20)
    tools = {f["tool"] for f in facts}
    assert "get_case" in tools
    assert "broken" not in tools
    fields = {f["field"] for f in facts if f["tool"] == "get_case"}
    assert "id" in fields or "status" in fields


def test_strict_violations_on_ack_warns():
    claims = [{"text": "ok", "source": "unknown"}]
    det = deterministic_claim_support(claims, [])
    v = strict_assurance_violations(
        claims=claims, det_support=det, ack_warns=["tool_x_error_not_acknowledged:bad"]
    )
    assert "tool_errors_not_acknowledged_in_prose" in v


def test_strict_violations_on_unsupported_tool_claim():
    tool_calls = [
        {"tool": "get_case", "args": {}, "result": {"case_id": "abc-123", "status": "open"}},
    ]
    claims = [
        {"text": "The sky is green.", "source": "tool"},
    ]
    det = deterministic_claim_support(claims, tool_calls)
    v = strict_assurance_violations(claims=claims, det_support=det, ack_warns=[])
    assert any(x.startswith("tool_claim_not_deterministically_supported") for x in v)


def test_format_assurance_refusal_non_empty():
    msg = format_assurance_refusal(["tool_errors_not_acknowledged_in_prose"])
    assert "strict assurance" in msg.lower()
    assert "source_refs" in msg.lower()


def test_review_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    review_store.reset_connection_for_tests()
    rid = review_store.save_review(
        turn_id="t1",
        tenant_id="tenant-a",
        analyst_id="analyst-1",
        status="approved",
        note="lgtm",
    )
    assert rid > 0
    row = review_store.latest_review("t1", "tenant-a")
    assert row is not None
    assert row["status"] == "approved"
    assert row["note"] == "lgtm"
    review_store.reset_connection_for_tests()
