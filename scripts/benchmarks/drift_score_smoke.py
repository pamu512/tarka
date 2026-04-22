#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

"""
Drift smoke: compare mean ml-scoring heuristic scores on two fixed feature batches.

Seeded "baseline" vs "shifted" distributions — asserts the scorer responds with a
minimum separation (guards against a dead or inverted signal path). Aligns with
roadmap drift / parity gates (lightweight CI, not full calibration).

Local mode (no server): imports ``heuristic_score`` from ``ml_scoring.heuristic`` (no FastAPI).

HTTP mode: POST /v1/score per row (optional; for integration tests).
"""

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_batch(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: expected non-empty JSON array of feature objects")
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: item {i} must be an object")
    return data


def _scores_local(features_list: list[dict[str, Any]]) -> list[float]:
    root = _repo_root()
    ms = root / "services" / "ml-scoring" / "src"
    sh = root / "services" / "shared"
    for p in (ms, sh):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    from ml_scoring.heuristic import heuristic_score  # noqa: PLC0415

    return [heuristic_score(f) for f in features_list]


def _scores_http(base_url: str, features_list: list[dict[str, Any]], timeout: float) -> list[float]:
    base = base_url.rstrip("/")
    out: list[float] = []
    for i, features in enumerate(features_list):
        body = json.dumps(
            {
                "tenant_id": "drift-smoke",
                "entity_id": f"entity-{i}",
                "event_type": "payment",
                "features": features,
            },
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/v1/score",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code} on /v1/score: {e.read().decode('utf-8', errors='replace')}") from e
        out.append(float(payload.get("score", 0)))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Drift smoke: baseline vs shifted heuristic score separation")
    p.add_argument("--baseline", type=Path, default=Path("scripts/benchmarks/fixtures/drift_baseline.json"))
    p.add_argument("--shifted", type=Path, default=Path("scripts/benchmarks/fixtures/drift_shifted.json"))
    p.add_argument("--min-delta", type=float, default=8.0, help="Minimum mean(shifted) - mean(baseline)")
    p.add_argument("--max-delta", type=float, default=95.0, help="Maximum allowed separation (sanity cap)")
    p.add_argument("--local", action="store_true", help="Use in-process heuristic_score (no HTTP)")
    p.add_argument("--url", default="", help="ml-scoring base URL (e.g. http://127.0.0.1:8005)")
    p.add_argument("--timeout", type=float, default=30.0)
    args = p.parse_args()

    root = _repo_root()
    baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
    shifted_path = args.shifted if args.shifted.is_absolute() else root / args.shifted

    b = _load_batch(baseline_path)
    s = _load_batch(shifted_path)

    if args.local:
        b_scores = _scores_local(b)
        s_scores = _scores_local(s)
    else:
        url = args.url.strip() or "http://127.0.0.1:8005"
        b_scores = _scores_http(url, b, args.timeout)
        s_scores = _scores_http(url, s, args.timeout)

    mb = statistics.mean(b_scores)
    ms = statistics.mean(s_scores)
    delta = ms - mb

    print(json.dumps({"mean_baseline": mb, "mean_shifted": ms, "delta": delta, "n_baseline": len(b), "n_shifted": len(s)}, indent=2))

    if delta < args.min_delta:
        print(
            f"FAIL: delta {delta:.4f} < min-delta {args.min_delta} (scorer may not respond to drift fixture)",
            file=sys.stderr,
        )
        return 1
    if delta > args.max_delta:
        print(f"FAIL: delta {delta:.4f} > max-delta {args.max_delta} (unexpected gap)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
