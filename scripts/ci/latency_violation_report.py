#!/usr/bin/env python3
"""Compare Criterion expanded p99 between Baseline and Proposed rule-set benchmarks.

Reads ``sample.json`` from each function's ``new/`` directory under a shared benchmark group
(e.g. ``target/criterion/rule_set_latency_guard/{baseline_evaluate,new}/sample.json``).

Exits with code ``1`` when::

    p99(proposed) - p99(baseline) > --max-delta-us (microseconds)

and prints a **Latency Violation Report** to stdout (and stderr summary).
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_CI_DIR = Path(__file__).resolve().parent
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))

from criterion_sample_stats import load_sample, weighted_p99_ns

US_NS = 1_000.0


def format_report(
    *,
    group_dir: Path,
    baseline_fn: str,
    proposed_fn: str,
    baseline_ns: float,
    proposed_ns: float,
    delta_ns: float,
    max_delta_ns: float,
    violated: bool,
) -> str:
    lines = [
        "=" * 80,
        "LATENCY VIOLATION REPORT" if violated else "LATENCY CHECK REPORT",
        "=" * 80,
        f"Criterion group directory: {group_dir}",
        "Metric: expanded per-iteration p99 (nearest rank over Criterion batches)",
        "",
        f"Baseline rule set (`{baseline_fn}`):",
        f"  p99 = {baseline_ns:.3f} ns  ({baseline_ns / US_NS:.3f} µs)",
        "",
        f"Proposed rule set (`{proposed_fn}`):",
        f"  p99 = {proposed_ns:.3f} ns  ({proposed_ns / US_NS:.3f} µs)",
        "",
        f"Delta (Proposed − Baseline): {delta_ns:+.3f} ns ({delta_ns / US_NS:+.3f} µs)",
        f"Allowed maximum delta: {max_delta_ns:.3f} ns ({max_delta_ns / US_NS:.3f} µs)",
        "",
    ]
    if violated:
        over = delta_ns - max_delta_ns
        lines.extend(
            [
                "RESULT: VIOLATION",
                f"  Proposed p99 exceeds Baseline by more than the threshold "
                f"(excess {over:.3f} ns = {over / US_NS:.3f} µs).",
            ]
        )
    else:
        lines.append("RESULT: OK — delta within threshold.")
    lines.append("=" * 80)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group-dir",
        type=Path,
        default=Path("target/criterion/rule_set_latency_guard"),
        help="Criterion benchmark group directory "
        "(contains one subdirectory per bench function)",
    )
    parser.add_argument(
        "--baseline-fn",
        default="baseline_evaluate",
        help="Subdirectory name for the Baseline rule set benchmark",
    )
    parser.add_argument(
        "--proposed-fn",
        default="proposed_evaluate",
        help="Subdirectory name for the Proposed rule set benchmark",
    )
    parser.add_argument(
        "--max-delta-us",
        type=float,
        default=100.0,
        help="Maximum allowed increase of Proposed p99 over Baseline (µs)",
    )
    args = parser.parse_args(argv)

    max_delta_ns = float(args.max_delta_us) * US_NS

    base_path = args.group_dir / args.baseline_fn / "new" / "sample.json"
    prop_path = args.group_dir / args.proposed_fn / "new" / "sample.json"

    if not base_path.is_file():
        print(f"ERROR: missing Baseline sample: {base_path}", file=sys.stderr)
        return 1
    if not prop_path.is_file():
        print(f"ERROR: missing Proposed sample: {prop_path}", file=sys.stderr)
        return 1

    try:
        b_times, b_iters = load_sample(base_path)
        p_times, p_iters = load_sample(prop_path)
        b99 = weighted_p99_ns(b_times, b_iters)
        p99 = weighted_p99_ns(p_times, p_iters)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    delta_ns = p99 - b99
    violated = delta_ns > max_delta_ns + 1e-9  # float tolerance

    # Treat NaN as failure
    if math.isnan(b99) or math.isnan(p99) or math.isnan(delta_ns):
        print("ERROR: invalid p99 (NaN)", file=sys.stderr)
        return 1

    report = format_report(
        group_dir=args.group_dir.resolve(),
        baseline_fn=args.baseline_fn,
        proposed_fn=args.proposed_fn,
        baseline_ns=b99,
        proposed_ns=p99,
        delta_ns=delta_ns,
        max_delta_ns=max_delta_ns,
        violated=violated,
    )
    print(report)
    if violated:
        print(
            f"REGRESSION: p99 delta {delta_ns / US_NS:.3f} µs exceeds "
            f"allowed {args.max_delta_us:.3f} µs",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
