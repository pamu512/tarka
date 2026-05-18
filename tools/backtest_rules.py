#!/usr/bin/env python3
"""
DuckDB backtesting harness: stream rows through the Rust rule engine (``tarka`` / ``tarka-core``).

Requires ``duckdb``, ``tarka`` (PyO3 wheel from ``crates/tarka-py``), and a Parquet file with at least
``amount`` (DOUBLE). Optional ``ground_truth`` / ``label`` column; otherwise labels are synthesized
from ``--truth-split`` (rows with ``amount > truth_split`` are treated as historical ``BLOCK``).

False positive rate (among rows whose ground truth is ALLOW):

    FP / (FP + TN)

Example::

    pip install duckdb 'tarka @ file:///${PWD}/crates/tarka-py/wheelhouse/...'   # or maturin develop

    python tools/backtest_rules.py \\
      --parquet tarka_v2_core/services/orchestrator/src/orchestrator/analytics/data/seed_data.parquet \\
      --block-if-amount-gt 5000 --truth-split 9000 --limit 10000
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_parquet() -> Path:
    return (
        _repo_root()
        / "tarka_v2_core"
        / "services"
        / "orchestrator"
        / "src"
        / "orchestrator"
        / "analytics"
        / "data"
        / "seed_data.parquet"
    )


def _json_default(o: Any) -> Any:
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def _build_compare_amount_rule(*, threshold: float, rule_id: str = "backtest.amount_gt") -> str:
    rule: dict[str, Any] = {
        "kind": "compare_leaf",
        "id": rule_id,
        "path": "/amount",
        "op": "gt",
        "expected": threshold,
    }
    return json.dumps(rule, separators=(",", ":"))


def _row_to_eval_payload(colnames: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in zip(colnames, row, strict=True):
        if k.lower() in ("ground_truth", "label", "historical_outcome"):
            continue
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _ground_truth_for_row(
    colnames: Sequence[str],
    row: Sequence[Any],
    *,
    label_column: str | None,
    truth_split: float,
) -> str:
    if label_column:
        idx = colnames.index(label_column)
        raw = row[idx]
        s = str(raw).strip().upper()
        if s in ("BLOCK", "FRAUD", "1", "TRUE", "POSITIVE"):
            return "BLOCK"
        if s in ("ALLOW", "LEGIT", "0", "FALSE", "NEGATIVE"):
            return "ALLOW"
        raise SystemExit(f"Unrecognized label value {raw!r} in column {label_column!r}")
    idx = colnames.index("amount")
    amt = float(row[idx])
    return "BLOCK" if amt > truth_split else "ALLOW"


def _print_table(title: str, rows: list[tuple[str, str, str]]) -> None:
    """Pretty-print a small 2–3 column table to stdout."""
    print(title)
    if not rows:
        return
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    w2 = max(len(r[2]) for r in rows)
    bar = "-" * (w0 + w1 + w2 + 10)
    print(bar)
    for r in rows:
        print(f"  {r[0]:<{w0}}  {r[1]:<{w1}}  {r[2]:<{w2}}")
    print(bar)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--parquet",
        type=Path,
        default=_default_parquet(),
        help="Parquet path (default: orchestrator seed_data.parquet).",
    )
    p.add_argument("--limit", type=int, default=10_000, help="Max rows to evaluate (default 10000).")
    p.add_argument(
        "--label-column",
        default="",
        help="Column with historical BLOCK/ALLOW (or fraud/legit). Empty → use --truth-split on amount.",
    )
    p.add_argument(
        "--truth-split",
        type=float,
        default=9000.0,
        help="When no label column: ground_truth=BLOCK iff amount > this (default 9000).",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--rule-json-file",
        type=Path,
        help="Path to a single RuleExpr JSON document (same schema as tarka-core ``RuleExpr``).",
    )
    g.add_argument(
        "--block-if-amount-gt",
        type=float,
        default=5000.0,
        help="Build a compare_leaf rule: BLOCK path when amount > this (default 5000).",
    )
    args = p.parse_args(argv)

    try:
        import duckdb
    except ImportError:
        print("backtest_rules: install duckdb:  pip install duckdb", file=sys.stderr)
        return 1

    pq = args.parquet.expanduser().resolve()
    if not pq.is_file():
        print(f"backtest_rules: parquet not found: {pq}", file=sys.stderr)
        return 1

    try:
        from tarka.decision import evaluate as tarka_evaluate
        from tarka.decision import rule_content_id
    except ImportError:
        print(
            "backtest_rules: Rust engine requires the ``tarka`` PyO3 package.\n"
            "  cd crates/tarka-py && maturin develop --release\n"
            "  (or pip install a compatible tarka wheel)",
            file=sys.stderr,
        )
        return 2

    if args.rule_json_file:
        rule_json = args.rule_json_file.read_text(encoding="utf-8").strip()
    else:
        rule_json = _build_compare_amount_rule(threshold=float(args.block_if_amount_gt))

    rule_hex = rule_content_id(rule_json)

    label_column = (args.label_column or "").strip() or None

    con = duckdb.connect(database=":memory:")
    limit = max(1, int(args.limit))
    con.execute(
        f"CREATE TABLE backtest_src AS SELECT * FROM read_parquet(?) LIMIT {limit}",
        [str(pq)],
    )
    meta = con.execute("SELECT * FROM backtest_src LIMIT 0")
    colnames = [d[0] for d in meta.description]
    if "amount" not in colnames:
        print("backtest_rules: dataset must include an ``amount`` column.", file=sys.stderr)
        return 1
    if label_column and label_column not in colnames:
        print(f"backtest_rules: label column {label_column!r} not in {colnames}", file=sys.stderr)
        return 1

    rows = con.execute("SELECT * FROM backtest_src").fetchall()
    n = len(rows)
    if n == 0:
        print("backtest_rules: no rows loaded.")
        return 0

    pred_block = pred_allow = 0
    tp = fp = fn = tn = 0
    errors = 0

    for row in rows:
        try:
            gt = _ground_truth_for_row(
                colnames,
                row,
                label_column=label_column,
                truth_split=float(args.truth_split),
            )
            payload = _row_to_eval_payload(colnames, row)
            data_json = json.dumps(payload, separators=(",", ":"), default=_json_default)
            dec = tarka_evaluate(rule_json, data_json, rule_hex, fast_path=True)
            predicted_block = bool(dec.decision) and not dec.is_partial
            if dec.is_partial:
                errors += 1
            if predicted_block:
                pred_block += 1
            else:
                pred_allow += 1

            if predicted_block and gt == "BLOCK":
                tp += 1
            elif predicted_block and gt == "ALLOW":
                fp += 1
            elif not predicted_block and gt == "BLOCK":
                fn += 1
            else:
                tn += 1
        except Exception:
            errors += 1

    denom_fp = fp + tn
    fp_rate = (fp / denom_fp) if denom_fp else 0.0

    print()
    print(f"  Rows evaluated:        {n}")
    print(f"  Rule engine errors:  {errors}")
    print()
    _print_table(
        "  Prediction counts (Rust: decision=True → BLOCK path)",
        [
            ("Metric", "Count", ""),
            ("Predicted BLOCK", str(pred_block), ""),
            ("Predicted ALLOW", str(pred_allow), ""),
        ],
    )
    print()
    _print_table(
        "  Ground truth × prediction (BLOCK = positive class)",
        [
            ("Actual / Pred", "Pred BLOCK", "Pred ALLOW"),
            ("Actual BLOCK", str(tp), str(fn)),
            ("Actual ALLOW", str(fp), str(tn)),
        ],
    )
    print()
    print(f"  False positive rate (FP / (FP+TN)), ground-truth ALLOW only:  {fp_rate:.4f}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
