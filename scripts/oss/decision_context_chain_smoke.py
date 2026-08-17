#!/usr/bin/env python3
"""Offline golden: evaluate → advise → human disposition chain."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tarka-dec-"))
    os.environ["DECISION_GRAPH_DB_PATH"] = str(tmp / "d.sqlite")
    os.environ["DECISION_GRAPH_ENABLED"] = "1"
    # Store path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "graph-service" / "src"))
    from graph_service.decision_context_store import (
        add_edge,
        get_chain,
        get_impact,
        record_decision,
    )

    a = record_decision(
        tenant_id="demo",
        kind="evaluate",
        category="transaction_evaluate",
        scenario="tx review",
        outcome="review",
        reasoning="velocity_spike",
        rule_ids=["velocity_spike"],
        entity_external_ids=["acct-1"],
    )
    b = record_decision(
        tenant_id="demo",
        kind="agent_advise",
        category="agent_run:chat",
        scenario="propose escalate",
        outcome="escalated",
        reasoning="ring evidence",
        agent_run_id="run-1",
        case_id="case-1",
    )
    add_edge("demo", a, b, "INFLUENCED")
    c = record_decision(
        tenant_id="demo",
        kind="human_disposition",
        category="case_status",
        scenario="confirm escalate",
        outcome="escalated",
        reasoning="analyst confirms",
        case_id="case-1",
    )
    add_edge("demo", b, c, "CAUSED")

    chain = get_chain("demo", c)
    ids = [n["external_id"] for n in chain["nodes"]]
    assert ids == [c, b, a], ids
    impact = get_impact("demo", a)
    assert {n["external_id"] for n in impact["nodes"]} == {a, b, c}

    # Semantica stub parity
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "semantica-bridge"))
    os.environ["SEMANTICA_BRIDGE_ENABLED"] = "1"
    from semantica_bridge import mirror_decision, stub_chain

    m1 = mirror_decision(
        category="transaction_evaluate",
        scenario="tx review",
        reasoning="velocity_spike",
        outcome="review",
    )
    m2 = mirror_decision(
        category="agent_run:chat",
        scenario="propose escalate",
        reasoning="ring",
        outcome="escalated",
        parent_semantica_id=m1.semantica_decision_id,
        relationship="INFLUENCED",
    )
    m3 = mirror_decision(
        category="case_status",
        scenario="confirm",
        reasoning="analyst",
        outcome="escalated",
        parent_semantica_id=m2.semantica_decision_id,
        relationship="CAUSED",
    )
    schain = stub_chain(m3.semantica_decision_id or "")
    assert len(schain["nodes"]) == 3, schain
    print("decision_context_chain_smoke: OK", {"native": ids, "semantica_stub": [n["id"] for n in schain["nodes"]]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
