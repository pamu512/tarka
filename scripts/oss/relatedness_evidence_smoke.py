#!/usr/bin/env python3
"""Track A finish: relatedness_evidence emits without geo (graph/device only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))

from decision_api.relatedness_evidence import (  # noqa: E402
    RELATEDNESS_SCHEMA_ID,
    build_relatedness_evidence,
)


def main() -> int:
    ev = build_relatedness_evidence(
        tags=["sdk:shared_device"],
        inference_context={},
        location_meta={},
        graph_meta={"seen_at_peer_count_24h": 2},
    )
    ok = (
        ev is not None
        and ev.get("schema_id") == RELATEDNESS_SCHEMA_ID
        and (ev.get("graph") or {}).get("seen_at_peer_count_24h") == 2
        and not (ev.get("geo_enrichment") or {}).get("copresence_risk")
    )
    print(json.dumps({"ok": ok, "schema_id": (ev or {}).get("schema_id")}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
