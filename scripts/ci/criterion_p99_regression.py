#!/usr/bin/env python3
"""Fail CI when Criterion tail latency regresses versus a saved baseline.

Reads Criterion ``sample.json`` files (``times`` + ``iters`` batches). For each batch ``i``,
per-iteration nanoseconds are approximated as ``times[i] / iters[i]``; that value is repeated
``int(iters[i])`` times so the multiset size matches measured iterations. The **p99** (nearest-rank)
of the expanded multiset approximates tail latency for the benchmarked closure.

Exit code ``1`` when ``new_p99 > baseline_p99 * max_ratio`` (default ``1.05``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CI_DIR = Path(__file__).resolve().parent
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))

from criterion_sample_stats import load_sample, weighted_p99_ns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        required=True,
        help="Criterion directory for one function, e.g. "
        "target/criterion/standard_heavy_rule_set/evaluate_full_trace",
    )
    parser.add_argument(
        "--baseline-label",
        default="main",
        help="Subdirectory name produced by `cargo bench -- --save-baseline <label>`",
    )
    parser.add_argument(
        "--max-ratio",
        type=float,
        default=1.05,
        help="Fail if new_p99 / baseline_p99 exceeds this (default: 1.05 = 5%% regression)",
    )
    args = parser.parse_args(argv)

    base_path = args.benchmark_dir / args.baseline_label / "sample.json"
    new_path = args.benchmark_dir / "new" / "sample.json"
    if not base_path.is_file():
        print(f"ERROR: missing baseline sample: {base_path}", file=sys.stderr)
        return 1
    if not new_path.is_file():
        print(f"ERROR: missing new sample: {new_path}", file=sys.stderr)
        return 1

    try:
        b_times, b_iters = load_sample(base_path)
        n_times, n_iters = load_sample(new_path)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    b99 = weighted_p99_ns(b_times, b_iters)
    n99 = weighted_p99_ns(n_times, n_iters)
    ratio = n99 / b99 if b99 > 0 else float("inf")

    print(
        "criterion expanded p99 (ns): "
        f"baseline={b99:.3f}  new={n99:.3f}  ratio={ratio:.6f}  "
        f"max_ratio={args.max_ratio:.6f}"
    )

    if ratio > args.max_ratio:
        print(
            f"REGRESSION: p99 ratio {ratio:.6f} exceeds max {args.max_ratio:.6f} "
            f"(baseline {b99:.3f} ns -> new {n99:.3f} ns)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
