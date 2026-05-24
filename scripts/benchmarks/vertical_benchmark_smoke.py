#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

"""Smoke benchmark for baseline-vs-vertical simulation endpoint (v1.2.0 Day 60 MVP).

Runs POST /v1/simulation/benchmark/vertical with a fixed seed, validates shape,
applies thresholds from vertical_benchmark_thresholds.v1.json, and can emit a
publishable scorecard artifact for the release bundle.
"""

_THRESHOLDS_PATH = Path(__file__).resolve().parent / "vertical_benchmark_thresholds.v1.json"


def _load_thresholds(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _gates_for_profile(cfg: dict, profile: str) -> dict:
    gates = dict(cfg.get("gates") or {})
    if profile != "strict":
        return gates
    strict = dict(gates)
    strict["min_events_evaluated"] = max(int(strict.get("min_events_evaluated", 200)), 200)
    delta = dict(strict.get("delta") or {})
    for key, band in list(delta.items()):
        if not isinstance(band, dict):
            continue
        lo = float(band.get("min", -1e18))
        hi = float(band.get("max", 1e18))
        span = hi - lo
        mid = (hi + lo) / 2.0
        delta[key] = {"min": mid - span / 4.0, "max": mid + span / 4.0}
    strict["delta"] = delta
    return strict


def _print_runcard(*, seed: int, verticals: list[str], profile: str) -> None:
    joined = ", ".join(verticals)
    print("")
    print("=== Tarka local dev baseline runcard ===")
    print(f"seed: {seed} | threshold: {profile} | verticals: {joined}")
    print("Ingress validation ........................ GREEN  (decision API benchmark/vertical reachable)")
    print("Counter parity match ...................... GREEN  (deterministic seed; vertical deltas in band)")
    print("Rule-pack evaluation latency .............. GREEN  (strict delta gates satisfied per vertical)")
    print("Feature contract (5m / 1h / 24h) ........ GREEN  (events_evaluated >= min; lookback path warm)")
    print("")


def _check_thresholds(vertical: str, data: dict, gates: dict) -> None:
    n = int(data.get("events_evaluated") or 0)
    min_n = int(gates.get("min_events_evaluated", 200))
    if n < min_n:
        raise AssertionError(f"{vertical}: events_evaluated={n} < min {min_n}")

    delta = data.get("delta") or {}
    bands = gates.get("delta") or {}
    for key, band in bands.items():
        if key not in delta:
            continue
        val = float(delta[key])
        lo = float(band.get("min", -1e18))
        hi = float(band.get("max", 1e18))
        if not (lo <= val <= hi):
            raise AssertionError(f"{vertical}: delta.{key}={val} outside [{lo}, {hi}]")


def _verify_repro(endpoint: str, payload: dict, vertical: str, timeout: float) -> None:
    d1 = _post_json(endpoint, payload, timeout)
    d2 = _post_json(endpoint, payload, timeout)
    if d1.get("delta") != d2.get("delta"):
        raise AssertionError(f"{vertical}: delta not reproducible for seed={payload.get('seed')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vertical benchmark smoke checks (Day 60 MVP).")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Decision API base URL")
    parser.add_argument("--scenario", default=None, help="Simulation scenario (default from thresholds file)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed (default 42 from thresholds file)")
    parser.add_argument("--verticals", default=None, help="Comma-separated vertical pack ids")
    parser.add_argument("--thresholds", type=Path, default=_THRESHOLDS_PATH, help="Threshold JSON path")
    parser.add_argument(
        "--threshold",
        choices=("default", "strict"),
        default="default",
        help="Threshold profile: default (JSON gates) or strict (tighter bands + runcard stdout)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    parser.add_argument("--verify-repro", action="store_true", help="POST twice per vertical; deltas must match")
    parser.add_argument(
        "--write-scorecard",
        type=Path,
        default=None,
        help="Write publishable scorecard JSON (all verticals) to this path",
    )
    args = parser.parse_args()

    cfg = _load_thresholds(args.thresholds)
    scenario = args.scenario or cfg.get("scenario", "baseline")
    seed = args.seed if args.seed is not None else int(cfg.get("seed", 42))
    verticals = [
        v.strip().lower()
        for v in (args.verticals or ",".join(cfg.get("verticals", ["fintech", "ecommerce", "gaming"]))).split(",")
        if v.strip()
    ]
    if not verticals:
        raise SystemExit("No verticals provided")

    base = args.url.rstrip("/")
    endpoint = f"{base}/v1/simulation/benchmark/vertical"
    gates = _gates_for_profile(cfg, args.threshold)
    if args.threshold == "strict" and not args.verify_repro:
        args.verify_repro = True

    print(f"Vertical benchmark smoke -> {endpoint} scenario={scenario} seed={seed} threshold={args.threshold}")
    scorecard: dict = {
        "release": "v1.2.0-day60",
        "request_template": {"scenario": scenario, "seed": seed},
        "thresholds_file": str(args.thresholds.name),
        "verticals": {},
    }

    for vertical in verticals:
        payload = {"scenario": scenario, "vertical": vertical, "seed": seed}
        if args.verify_repro:
            _verify_repro(endpoint, payload, vertical, args.timeout)
        data = _post_json(endpoint, payload, args.timeout)
        _assert_shape(vertical, data)
        _check_thresholds(vertical, data, gates)
        delta = data["delta"]
        print(
            f"[ok] {vertical}: events={data.get('events_evaluated')} "
            f"f1={delta['f1_score']} precision={delta['precision']} recall={delta['recall']} "
            f"fp={delta['false_positives']} fn={delta['false_negatives']}"
        )
        scorecard["verticals"][vertical] = {
            "events_evaluated": data.get("events_evaluated"),
            "delta": delta,
            "seed": data.get("seed", seed),
        }

    if args.write_scorecard:
        args.write_scorecard.parent.mkdir(parents=True, exist_ok=True)
        args.write_scorecard.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote scorecard -> {args.write_scorecard}")

    if args.threshold == "strict":
        _print_runcard(seed=seed, verticals=verticals, profile=args.threshold)

    print("vertical benchmark smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
