#!/usr/bin/env python3
"""Golden analyst loop smoke (maturity Wave 1): evaluate → disposition labels → calibration join.

Does not require full stack for unit-style dry-run; with DECISION_API_URL set, hits live APIs.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    # Always run offline unit of the join helpers.
    sys.path.insert(
        0,
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "services",
            "decision-api",
            "src",
        ),
    )
    from decision_api.label_join import apply_y_labels, label_coverage_posture
    from decision_api.reliability_export import reliability_bins

    rows = [
        {
            "trace_id": "demo-1",
            "entity_id": "u1",
            "y_label": "",
            "proxy_label_from_decision": "1",
            "score": "90",
            "integrity_confidence": "0.9",
        }
    ]
    apply_y_labels(rows, {"demo-1": "1"})
    bins = reliability_bins(rows, n_bins=5, use_proxy_labels=False)
    posture = label_coverage_posture(
        label_coverage=float(bins["label_coverage"]), proxy_only=False
    )
    assert posture["healthy"] is True, posture
    print("offline golden label join: OK", json.dumps(posture))

    base = os.environ.get("DECISION_API_URL", "").rstrip("/")
    require_live = os.environ.get("REQUIRE_DECISION_API", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not base:
        if require_live:
            print("REQUIRE_DECISION_API set but DECISION_API_URL unset", file=sys.stderr)
            return 1
        print("DECISION_API_URL unset — offline check only")
        return 0

    try:
        ev = _post(
            f"{base}/v1/decisions/evaluate",
            {
                "tenant_id": "demo",
                "event_type": "payment",
                "entity_id": "golden-loop-user",
                "payload": {"amount": 42.0, "currency": "USD"},
                "metadata": {"shadow": False},
            },
        )
        tid = str(ev.get("trace_id") or "")
        print("evaluate trace_id=", tid, "decision=", ev.get("decision"))
        bins_live = _post(
            f"{base}/v1/calibration/reliability-bins?tenant_id=demo&n_bins=5",
            {
                "labels_by_trace": {tid: "LEGITIMATE"} if tid else {},
                "allow_proxy_labels": False,
            },
        )
        print("reliability posture=", bins_live.get("posture"))
        status = _get(f"{base}/v1/ops/calibration-status?tenant_id=demo")
        print(
            "calibration-status healthy=",
            status.get("healthy"),
            status.get("label_coverage"),
        )
        posture = bins_live.get("posture") if isinstance(bins_live, dict) else None
        if isinstance(posture, dict) and posture.get("healthy") is False:
            print("live reliability posture unhealthy", posture, file=sys.stderr)
            return 1
    except urllib.error.URLError as e:
        print("live API unreachable:", e, file=sys.stderr)
        return 1
    except Exception as e:
        print("live golden loop failed:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
