"""Evidence bundle v0/v1/dual formats."""

from investigation_agent.evidence_bundle import build_evidence_bundle_draft
from investigation_agent.integration_contract import INTEGRATION_CONTRACT_VERSION


def test_evidence_bundle_v0_legacy_shape():
    d = build_evidence_bundle_draft(
        reply="hello",
        claims=[{"text": "c", "source": "tool"}],
        source_refs=[],
        answer_sections={},
        claims_analysis=[],
        tool_calls=[{"tool": "get_case", "args": {"case_id": "1"}, "result": {}}],
        prompt_version="3.2.0",
        playbook_id=None,
        turn_id="t1",
        bundle_format="v0",
        contract_version=INTEGRATION_CONTRACT_VERSION,
    )
    assert d["schema_hint"] == "tarka.evidence_bundle_draft/v0"
    assert "schema_id" not in d
    assert "contract_version" not in d


def test_evidence_bundle_dual_has_v0_and_v1():
    d = build_evidence_bundle_draft(
        reply="hello",
        claims=[],
        source_refs=[],
        answer_sections={},
        claims_analysis=[],
        tool_calls=[{"tool": "get_case", "args": {"x": 1}, "result": {}}],
        prompt_version="3.2.0",
        playbook_id=None,
        turn_id="turn-abc",
        bundle_format="dual",
        contract_version=INTEGRATION_CONTRACT_VERSION,
        agent_build="test-build",
        redaction_level="analyst_view",
    )
    assert d["schema_hint"] == "tarka.evidence_bundle_draft/v0"
    assert d["schema_id"] == "tarka.evidence_bundle/v1"
    assert d["contract_version"] == INTEGRATION_CONTRACT_VERSION
    assert d["agent_build"] == "test-build"
    assert d["redaction_level"] == "analyst_view"
    assert len(d["tool_trace_redacted"]) == 1
    assert d["tool_trace_redacted"][0]["tool"] == "get_case"
    assert len(d["tool_trace_redacted"][0]["args_sha256"]) == 64
    assert len(d["content_sha256"]) == 64


def test_evidence_bundle_v1_no_legacy_hint():
    d = build_evidence_bundle_draft(
        reply="x",
        claims=[],
        source_refs=[],
        answer_sections={},
        claims_analysis=[],
        tool_calls=[],
        prompt_version="1",
        playbook_id=None,
        turn_id="t",
        bundle_format="v1",
        contract_version="1.1.0",
    )
    assert d["schema_id"] == "tarka.evidence_bundle/v1"
    assert "schema_hint" not in d
