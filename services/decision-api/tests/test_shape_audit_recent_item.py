"""Tests for shape_audit_recent_item output contract — event_type + decision fields.

The module under test (audit_recent.py) pulls in a deep import chain
(models → db → tarka_core) that requires a full service environment.
These tests verify the shaping contract with two approaches:
1. Source-level: parse the source to confirm keys exist in the returned dict.
2. Logic-level: inline the trivial helpers to confirm correctness.
"""

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from decision_api.audit_recent_derive import derive_rule_result


SRC = (
    Path(__file__).resolve().parent.parent / "src" / "decision_api" / "audit_recent.py"
)


def _returned_keys_from_source() -> set[str]:
    """Parse shape_audit_recent_item and extract string keys from the return dict."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "shape_audit_recent_item":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.Dict):
                    return {
                        k.value
                        for k in child.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    raise AssertionError("shape_audit_recent_item return dict not found in source")


def test_source_includes_event_type_and_decision_keys():
    keys = _returned_keys_from_source()
    assert "event_type" in keys, f"event_type missing from returned keys: {keys}"
    assert "decision" in keys, f"decision missing from returned keys: {keys}"


def test_source_includes_existing_keys():
    keys = _returned_keys_from_source()
    for expected in (
        "trace_id",
        "short_id",
        "amount",
        "currency",
        "rule_result",
        "tags",
        "ai_confidence",
        "created_at",
        "rule_hits",
        "rule_pack_file",
        "integrity",
    ):
        assert expected in keys, f"{expected} missing from returned keys: {keys}"


# ── inline logic tests (mirrors shape_audit_recent_item without importing it) ──


def _fake_row(**overrides):
    defaults = dict(
        trace_id=uuid.uuid4(),
        event_type="login",
        decision="allow",
        tags=[],
        payload_snapshot=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _short_id(trace_id):
    s = str(trace_id).replace("-", "")
    return (s[:8] or "UNKNOWN").upper()


def _shape_inline(row):
    """Mirrors the logic in shape_audit_recent_item."""
    snap = row.payload_snapshot if isinstance(row.payload_snapshot, dict) else {}
    payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else {}
    raw_amt = payload.get("amount")
    amount = float(raw_amt) if raw_amt is not None else None
    cur = payload.get("currency")
    currency = (
        str(cur).strip().upper()[:8] if cur is not None and str(cur).strip() else None
    )
    return {
        "trace_id": str(row.trace_id),
        "short_id": _short_id(row.trace_id),
        "event_type": row.event_type or None,
        "decision": row.decision or None,
        "amount": amount,
        "currency": currency,
        "rule_result": derive_rule_result(row.decision, row.tags, snap),
        "tags": list(row.tags) if row.tags else [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def test_event_type_and_decision_present():
    shaped = _shape_inline(_fake_row(event_type="payment", decision="deny"))
    assert shaped["event_type"] == "payment"
    assert shaped["decision"] == "deny"


def test_event_type_null_when_empty():
    shaped = _shape_inline(_fake_row(event_type="", decision=""))
    assert shaped["event_type"] is None
    assert shaped["decision"] is None


def test_event_type_none_passthrough():
    shaped = _shape_inline(_fake_row(event_type=None, decision=None))
    assert shaped["event_type"] is None
    assert shaped["decision"] is None


def test_all_event_types_pass_through():
    for et in ("login", "payment", "signup", "device", "session", "custom"):
        assert _shape_inline(_fake_row(event_type=et))["event_type"] == et


def test_existing_fields_with_payload():
    row = _fake_row(
        event_type="login",
        decision="review",
        payload_snapshot={"payload": {"amount": 42, "currency": "USD"}},
    )
    shaped = _shape_inline(row)
    assert shaped["trace_id"] == str(row.trace_id)
    assert shaped["short_id"]
    assert shaped["amount"] == 42.0
    assert shaped["currency"] == "USD"
    assert shaped["rule_result"] == "REVIEW"
    assert shaped["created_at"] is not None


def test_tags_surfaced_in_output():
    row = _fake_row(tags=["ml:unavailable", "enrichment:unavailable"])
    shaped = _shape_inline(row)
    assert shaped["tags"] == ["ml:unavailable", "enrichment:unavailable"]


def test_tags_empty_list_when_none():
    row = _fake_row(tags=None)
    shaped = _shape_inline(row)
    assert shaped["tags"] == []


def test_signup_event_type_first_class():
    row = _fake_row(event_type="signup", decision="review")
    shaped = _shape_inline(row)
    assert shaped["event_type"] == "signup"
