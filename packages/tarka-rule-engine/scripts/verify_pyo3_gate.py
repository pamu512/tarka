#!/usr/bin/env python3
"""Gate: ``maturin develop`` (optionally ``--extras api`` for HTTP helpers) then run this script."""

from __future__ import annotations


def main() -> None:
    import tarka_rule_engine

    eng = tarka_rule_engine.RuleEngine()
    out = eng.evaluate(0.375, 42)
    assert float(out["graph_score"]) == 0.375
    assert int(out["velocity_1h"]) == 42
    assert out["ok"] is True
    assert out.get("decision") == "ALLOW"

    ctx = tarka_rule_engine.EvaluationContext(0.5, 99)
    assert ctx.graph_score == 0.5
    assert ctx.velocity_1h == 99

    print("verify_pyo3_gate_ok", dict(out))


if __name__ == "__main__":
    main()
