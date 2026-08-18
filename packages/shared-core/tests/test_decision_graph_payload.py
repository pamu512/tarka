"""Tests for decision graph payload builders."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_payload():
    path = Path(__file__).resolve().parents[1] / "tarka_shared" / "decision_graph_payload.py"
    spec = importlib.util.spec_from_file_location("decision_graph_payload", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_evaluate_payload_includes_entities():
    mod = _load_payload()
    payload = mod.build_evaluate_payload(
        tenant_id="t1",
        trace_id="tr-1",
        entity_id="acct-1",
        event_type="payment",
        decision="review",
        score=0.8,
        rule_hits=["velocity_spike"],
        fallback_reason=None,
        payload={"device_id": "dev-9"},
        metadata={},
        decision_log_record={"id": "al-99"},
        shadow_request=False,
    )
    assert payload["kind"] == "evaluate"
    assert payload["outcome"] == "review"
    assert "acct-1" in payload["entity_external_ids"]
    assert "dev-9" in payload["entity_external_ids"]
    assert payload["audit_log_id"] == "al-99"


def test_build_human_disposition_payload_edges():
    mod = _load_payload()
    payload = mod.build_human_disposition_payload(
        tenant_id="t1",
        case_id="case-1",
        entity_id="acct-1",
        trace_id="tr-1",
        status="escalated",
        actor_id="analyst-1",
        reason_code="ring_evidence",
        prior_decision_id="dec-parent",
    )
    assert payload["kind"] == "human_disposition"
    assert payload["edges"][0]["from_external_id"] == "dec-parent"
    assert payload["edges"][0]["relationship"] == "CAUSED"
