#!/usr/bin/env python3
"""Wave 5: partner fusion fixture smoke (no live Fingerprint/Incognia keys)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "partner_fusion_signals.json"


def main() -> int:
    sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))
    from decision_api.partner_fusion import graph_writeback_hints, signals_to_feature_tags

    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sigs = [SimpleNamespace(**row) for row in raw["signals"]]
    feats, tags, evidence = signals_to_feature_tags(sigs)
    hints = graph_writeback_hints(
        tenant_id="fixture-tenant",
        entity_id="fixture-entity",
        transaction_id="fixture-tx",
        tags=tags,
        features=feats,
    )
    ok = (
        bool(feats.get("vendor_fingerprint_id"))
        and bool(feats.get("vendor_incognia_place_id"))
        and len(evidence) >= 2
        and len(hints.get("vertices") or []) >= 2
        and len(hints.get("edges") or []) >= 2
    )
    out = {
        "ok": ok,
        "feature_keys": sorted(feats.keys()),
        "tags": tags,
        "evidence_n": len(evidence),
        "vertices_n": len(hints.get("vertices") or []),
        "edges_n": len(hints.get("edges") or []),
    }
    print(json.dumps(out, indent=2))
    art = os.environ.get("PARTNER_FUSION_ARTIFACT", "").strip()
    if art:
        path = Path(art)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
