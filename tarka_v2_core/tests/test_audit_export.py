"""Tests for redacted ``export-audit`` JSON."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parents[2]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from tarka_v2_core.audit_export import (  # noqa: E402
    REDACTED,
    mask_agent_notes,
    mask_code_executed,
    mask_shadow_decision,
    mask_transaction_schema,
    run_export_audit,
)


def test_mask_transaction_schema_redacts_entity_id_and_metadata_strings() -> None:
    eid = str(uuid.uuid4())
    tx = {
        "entity_id": eid,
        "amount": 50.0,
        "timestamp": "2026-05-01T12:00:00+00:00",
        "metadata": {"email": "victim@example.com", "channel": "wire", "score": 0.2},
    }
    out = mask_transaction_schema(tx)
    assert out["entity_id"] == REDACTED
    assert out["timestamp"] == REDACTED
    assert out["amount"] == 50.0
    assert out["metadata"]["email"] == REDACTED
    assert out["metadata"]["channel"] == REDACTED
    assert out["metadata"]["score"] == 0.2


def test_mask_shadow_decision_preserves_reasoning() -> None:
    tid = str(uuid.uuid4())
    d = {
        "transaction_id": tid,
        "risk_score": 42.0,
        "is_fraud": True,
        "reasoning": ["Velocity spike on new device", "Mule pattern"],
        "confidence_metrics": {"x": 1},
    }
    out = mask_shadow_decision(d)
    assert out["transaction_id"] == REDACTED
    assert out["reasoning"] == ["Velocity spike on new device", "Mule pattern"]
    assert out["risk_score"] == 42.0


def test_mask_agent_notes_json_roundtrip() -> None:
    tid = str(uuid.uuid4())
    raw = json.dumps(
        {
            "transaction_id": tid,
            "risk_score": 1.0,
            "is_fraud": False,
            "reasoning": ["Legitimate recurring merchant"],
            "confidence_metrics": {},
        }
    )
    out = mask_agent_notes(raw)
    parsed = json.loads(out or "{}")
    assert parsed["transaction_id"] == REDACTED
    assert parsed["reasoning"] == ["Legitimate recurring merchant"]


def test_mask_code_executed_messages_embedded_transaction(tmp_path: Path) -> None:
    eid = str(uuid.uuid4())
    messages = [
        {
            "role": "system",
            "content": json.dumps(
                {
                    "entity_id": eid,
                    "amount": 500.0,
                    "timestamp": "2026-05-09T12:00:00+00:00",
                    "metadata": {"note": "sensitive string"},
                }
            ),
        }
    ]
    raw = json.dumps(messages)
    out = mask_code_executed(raw)
    parsed = json.loads(out or "[]")
    inner = json.loads(parsed[0]["content"])
    assert inner["entity_id"] == REDACTED
    assert inner["metadata"]["note"] == REDACTED


def test_run_export_audit_sqlite_integration(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.db"
    url = f"sqlite+pysqlite:///{db_path}"
    from sqlalchemy import create_engine, text

    eng = create_engine(url, future=True)
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE audit_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "case_id VARCHAR(36) NOT NULL,"
                "action_taken TEXT NOT NULL,"
                "code_executed TEXT,"
                "agent_notes TEXT,"
                "timestamp TEXT"
                ")"
            )
        )
        cid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        action = json.dumps({"transaction_id": tid, "amount": 10.0, "is_fraud": False})
        notes = json.dumps(
            {
                "transaction_id": tid,
                "risk_score": 0.5,
                "is_fraud": False,
                "reasoning": ["KEEP_ME_REASON"],
                "confidence_metrics": {},
            }
        )
        conn.execute(
            text(
                "INSERT INTO audit_logs (case_id, action_taken, code_executed, agent_notes, timestamp) "
                "VALUES (:c, :a, :code, :notes, :ts)"
            ),
            {
                "c": cid,
                "a": action,
                "code": "[]",
                "notes": notes,
                "ts": "2026-01-01T00:00:00Z",
            },
        )

    out_json = tmp_path / "export.json"
    import os

    old = os.environ.get("SHADOW_DATABASE_URL")
    try:
        os.environ["SHADOW_DATABASE_URL"] = url
        run_export_audit(out_json, limit=100)
    finally:
        if old is None:
            os.environ.pop("SHADOW_DATABASE_URL", None)
        else:
            os.environ["SHADOW_DATABASE_URL"] = old

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["row_count"] == 1
    row = data["rows"][0]
    assert row["case_id"] == REDACTED
    assert REDACTED in (row.get("action_taken") or "")
    assert "KEEP_ME_REASON" in (row.get("agent_notes") or "")
    assert tid not in (row.get("agent_notes") or "")
    assert tid not in (row.get("action_taken") or "")
