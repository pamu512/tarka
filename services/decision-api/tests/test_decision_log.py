from __future__ import annotations

import json

import pytest
from decision_api.config import settings
from decision_api.decision_log import build_decision_log_record, emit_decision_log


def _record(trace_id: str, *, artifact_manifest: dict | None = None) -> dict:
    return build_decision_log_record(
        trace_id=trace_id,
        tenant_id="tenant-a",
        entity_id="entity-1",
        event_type="payment",
        decision="review",
        score=61.2,
        tags=["sdk:vpn"],
        rule_hits=["rule:velocity_guard"],
        reasons=["rule:velocity_guard"],
        ml_score=55.0,
        inference_context={"schema_version": "3"},
        recommended_action="step_up_mfa",
        challenge_policy_id="default_v1",
        challenge_metadata={"ladder": ["mfa"]},
        fallback_reason=None,
        payload_snapshot={"payload": {"amount": 100}},
        artifact_manifest=artifact_manifest,
    )


@pytest.mark.asyncio
async def test_emit_decision_log_appends_hash_chain(tmp_path, monkeypatch):
    path = tmp_path / "decision-log.jsonl"
    monkeypatch.setattr(settings, "decision_log_enabled", True)
    monkeypatch.setattr(settings, "decision_log_path", str(path))
    monkeypatch.setattr(settings, "decision_log_warehouse_url", "")
    monkeypatch.setattr(settings, "decision_log_warehouse_api_key", "")

    await emit_decision_log(_record("trace-1", artifact_manifest={"ml_model": "m1"}))
    await emit_decision_log(_record("trace-2", artifact_manifest={"ml_model": "m2"}))

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2
    assert rows[0]["artifact_manifest"]["ml_model"] == "m1"
    assert isinstance(rows[0].get("record_hash"), str) and rows[0]["record_hash"]
    assert rows[1].get("previous_record_hash") == rows[0]["record_hash"]
