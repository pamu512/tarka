#!/usr/bin/env python3
"""
Fail CI/local checks if signal catalogs drift or are structurally invalid.

Run from repo root: python scripts/ml/validate_signal_catalogs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS_ML = Path(__file__).resolve().parent
if str(_SCRIPTS_ML) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ML))
from feature_order import get_feature_order, repo_root  # noqa: E402


def _check_horizontal(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("catalog_id") != "horizontal_session_v1":
        print(f"{path.name}: expected catalog_id horizontal_session_v1", file=sys.stderr)
        return 1
    feats = data.get("features")
    if not isinstance(feats, dict) or len(feats) < 3:
        print(f"{path.name}: features must be a non-empty object", file=sys.stderr)
        return 1
    if "event_count_5m" not in feats:
        print(f"{path.name}: missing event_count_5m (required for burst rules)", file=sys.stderr)
        return 1
    print(f"OK: {path.name} structure")
    return 0


def main() -> int:
    root = repo_root()
    pay = root / "contracts" / "signal-catalog" / "payment_card_cnp_v1.json"
    hor = root / "contracts" / "signal-catalog" / "horizontal_session_v1.json"
    if not pay.is_file():
        print(f"Missing {pay}", file=sys.stderr)
        return 1
    data = json.loads(pay.read_text(encoding="utf-8"))
    order = (data.get("ml_scoring_feature_vector") or {}).get("order")
    if not order:
        print("payment_card_cnp_v1: missing ml_scoring_feature_vector.order", file=sys.stderr)
        return 1

    code_order = get_feature_order()
    if list(order) != list(code_order):
        print("Drift: catalog order != ml_scoring.heuristic.FEATURE_ORDER", file=sys.stderr)
        print("  catalog: ", order, file=sys.stderr)
        print("  code:    ", code_order, file=sys.stderr)
        return 1
    print("OK: payment_card_cnp_v1.ml_scoring_feature_vector.order matches heuristic.FEATURE_ORDER")

    if not hor.is_file():
        print(f"Missing {hor}", file=sys.stderr)
        return 1
    if _check_horizontal(hor) != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
