"""P2: marketplace demo tenant proof smoke + FPR helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "marketplace_demo_tenant_proof.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("marketplace_demo_tenant_proof", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compute_hold_fpr():
    mod = _load_mod()
    out = mod.compute_hold_fpr(
        [
            {"predicted_hold": True, "y_label": "1"},
            {"predicted_hold": True, "y_label": "0"},
            {"predicted_hold": False, "y_label": "0"},
        ]
    )
    assert out["holds"] == 2
    assert out["false_positives"] == 1
    assert out["false_positive_rate"] == 0.5


def test_marketplace_demo_tenant_proof_ok():
    mod = _load_mod()
    import asyncio

    out = asyncio.run(mod.run_proof())
    assert out["tenant_id"] == "mkt-demo-2026"
    assert out["ok"] is True
    assert out["boards"]["payout"]["ok"] is True
    assert out["boards"]["promo"]["ok"] is True
    assert out["boards"]["seller"]["ok"] is True
    assert out["collusion"]["ok"] is True
    assert out["false_positive"]["false_positive_rate"] <= 0.25
