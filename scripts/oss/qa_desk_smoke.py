#!/usr/bin/env python3
"""Wave 5: QA sampling helpers. Route wiring is tested in case-api TestClient."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.path.insert(0, str(_REPO / "services" / "case-api" / "src"))
    from case_api.qa_sampling import disagreement_metrics, sample_case_ids

    ids = [f"c{i}" for i in range(40)]
    a = sample_case_ids(ids, rate=0.1, seed="wave5", limit=10)
    b = sample_case_ids(ids, rate=0.1, seed="wave5", limit=10)
    assert a == b and a, "sample must be deterministic and non-empty"
    metrics = disagreement_metrics(
        [
            {"original_status": "resolved", "qa_status": "resolved"},
            {"original_status": "resolved", "qa_status": "closed"},
        ]
    )
    assert metrics["reviewed"] == 2
    assert metrics["disagree"] == 1

    out = {
        "ok": True,
        "sampled": len(a),
        "agreement_rate": metrics["agreement_rate"],
    }
    print(json.dumps(out))

    base = os.environ.get("CASE_API_URL", "").rstrip("/")
    if not base:
        return 0
    try:
        url = f"{base}/v1/cases/ops/qa-metrics?tenant_id=demo"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        print("live qa-metrics keys=", sorted(body.keys())[:12])
    except urllib.error.URLError as e:
        print("live case-api unreachable:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
