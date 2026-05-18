#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

"""Smoke benchmark for baseline-vs-vertical simulation endpoint.

Runs /v1/simulation/benchmark/vertical for selected vertical packs and validates
response shape for deterministic CI checks.
"""


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def _assert_shape(vertical: str, data: dict) -> None:
    required_top = {"scenario", "vertical", "baseline", "vertical_pack", "delta"}
    missing = required_top - set(data.keys())
    if missing:
        raise AssertionError(f"{vertical}: missing top-level keys: {sorted(missing)}")
    if str(data.get("vertical", "")).lower() != vertical:
        raise AssertionError(f"{vertical}: response vertical mismatch: {data.get('vertical')}")

    metric_keys = {
        "precision",
        "recall",
        "f1_score",
        "score_separation",
        "false_positives",
        "false_negatives",
    }
    delta = data.get("delta", {})
    if not isinstance(delta, dict):
        raise AssertionError(f"{vertical}: delta must be object")
    missing_delta = metric_keys - set(delta.keys())
    if missing_delta:
        raise AssertionError(f"{vertical}: missing delta keys: {sorted(missing_delta)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vertical benchmark smoke checks.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Decision API base URL")
    parser.add_argument("--scenario", default="baseline", help="Simulation scenario")
    parser.add_argument(
        "--verticals", default="fintech,ecommerce,gaming", help="Comma-separated vertical pack ids"
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    endpoint = f"{base}/v1/simulation/benchmark/vertical"
    verticals = [v.strip().lower() for v in args.verticals.split(",") if v.strip()]
    if not verticals:
        raise SystemExit("No verticals provided")

    print(f"Vertical benchmark smoke -> {endpoint} (scenario={args.scenario})")
    for vertical in verticals:
        payload = {"scenario": args.scenario, "vertical": vertical}
        data = _post_json(endpoint, payload, timeout=args.timeout)
        _assert_shape(vertical, data)
        delta = data["delta"]
        print(
            f"[ok] {vertical}: "
            f"f1={delta['f1_score']} "
            f"precision={delta['precision']} "
            f"recall={delta['recall']} "
            f"fp={delta['false_positives']} "
            f"fn={delta['false_negatives']}"
        )

    print("vertical benchmark smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
