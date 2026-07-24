"""Phase 3: exact evidence-id citation validation."""

from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from decision_intelligence import (  # noqa: E402
    make_evidence_item,
    new_agent_run,
    validate_claims_against_evidence,
)


def test_validate_claims_requires_exact_evidence_ids() -> None:
    ev = make_evidence_item(
        source="decision_audit",
        json_pointer="/payload_snapshot/decision_evidence/feature_map/amount",
        value=9500,
    )
    ok, adj = validate_claims_against_evidence(
        [{"text": "amount high", "evidence_ids": [ev.evidence_id]}],
        {ev.evidence_id: ev},
    )
    assert ok[0]["supported"] is True
    assert adj == []

    bad, adj2 = validate_claims_against_evidence(
        [{"text": "guess", "evidence_ids": ["ev_missing"]}],
        {ev.evidence_id: ev},
    )
    assert bad[0]["supported"] is False
    assert "unresolved_evidence_id" in adj2


def test_agent_run_is_tenant_scoped() -> None:
    run = new_agent_run(
        tenant_id="demo",
        prompt="summarize",
        model_provider="ollama",
        model_revision="local",
        case_id="c1",
        evidence_ids=["ev_abc"],
    )
    d = run.to_dict()
    assert d["tenant_id"] == "demo"
    assert d["evidence_ids"] == ["ev_abc"]
    assert d["prompt_hash"]
