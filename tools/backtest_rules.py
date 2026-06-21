#!/usr/bin/env python3
"""
Backtesting harness backed by the native ``tarka batch-replay`` CLI (``tarka-cli``).

All rule simulations run through the compiled Rust batch-replay engine via ``subprocess.run``,
matching production forensic replay and removing PyO3 / in-process engine variance.

Requires a ClickHouse ``evidence_manifests`` window with audit rows for the tenant. Optional
Parquet input is used only to derive ``--since`` / ``--until`` bounds (not for per-row evaluation).

False positive rate (when ground-truth confusion counts are supplied or embedded under
``display.ground_truth_confusion`` in a scorecard artifact):

    FP / (FP + TN)

Example::

    python tools/backtest_rules.py \\
      --tenant parity-demo \\
      --since 2026-05-01T00:00:00Z \\
      --until 2026-05-02T00:00:00Z \\
      --rule-json-file ./rules/amount_block.json

    python tools/backtest_rules.py \\
      --parquet services/orchestrator/src/orchestrator/analytics/data/seed_data.parquet \\
      --tenant default \\
      --timestamp-column event_time \\
      --block-if-amount-gt 5000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_parquet() -> Path:
    return (
        _repo_root()
        / "services"
        / "orchestrator"
        / "src"
        / "orchestrator"
        / "analytics"
        / "data"
        / "seed_data.parquet"
    )


def _default_tarka_bin() -> str:
    explicit = os.environ.get("TARKA_BIN", "").strip()
    if explicit:
        return explicit
    found = shutil.which("tarka")
    if found:
        return found
    for candidate in (
        _repo_root() / "target" / "debug" / "tarka",
        _repo_root() / "target" / "release" / "tarka",
    ):
        if candidate.is_file():
            return str(candidate)
    return "tarka"


def _build_compare_amount_rule(*, threshold: float, rule_id: str = "backtest.amount_gt") -> str:
    rule: dict[str, Any] = {
        "kind": "compare_leaf",
        "id": rule_id,
        "path": "/amount",
        "op": "gt",
        "expected": threshold,
    }
    return json.dumps(rule, separators=(",", ":"))


def _rule_content_id_hex(rule_json: str) -> str:
    return hashlib.sha256(rule_json.encode("utf-8")).hexdigest()


def _print_table(title: str, rows: list[tuple[str, str, str]]) -> None:
    print(title)
    if not rows:
        return
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    w2 = max(len(r[2]) for r in rows)
    bar = "-" * (w0 + w1 + w2 + 10)
    print(bar)
    for row in rows:
        print(f"  {row[0]:<{w0}}  {row[1]:<{w1}}  {row[2]:<{w2}}")
    print(bar)


@dataclass(frozen=True)
class ConfusionCounts:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def predicted_block(self) -> int:
        return self.tp + self.fp

    @property
    def predicted_allow(self) -> int:
        return self.tn + self.fn

    def false_positive_rate(self) -> float:
        denom = self.fp + self.tn
        return (self.fp / denom) if denom else 0.0


@dataclass(frozen=True)
class BacktestReport:
    engine_label: str
    tenant_id: str
    since: str
    until: str
    total_evaluated: int
    decision_match_count: int
    step_parity_count: int
    mismatch_count: int
    false_positive_rate_delta: float
    precision_delta: float
    recall_delta: float
    execution_time_ms: int
    replay_predicted_block: int | None
    replay_predicted_allow: int | None
    ground_truth: ConfusionCounts | None
    audit_reference: ConfusionCounts | None
    partial_audit_note: str | None = None


def _parse_confusion(raw: Mapping[str, Any]) -> ConfusionCounts | None:
    keys = ("tp", "fp", "fn", "tn")
    if not all(k in raw for k in keys):
        return None
    try:
        return ConfusionCounts(
            tp=int(raw["tp"]),
            fp=int(raw["fp"]),
            fn=int(raw["fn"]),
            tn=int(raw["tn"]),
        )
    except (TypeError, ValueError):
        return None


def _audit_confusion_from_mismatches(scorecard: Mapping[str, Any]) -> tuple[ConfusionCounts, bool]:
    """Build audit (historical) vs replay confusion from scorecard mismatch rows only."""
    tp = fp = fn = tn = 0
    mismatches = scorecard.get("mismatches")
    if not isinstance(mismatches, list):
        return ConfusionCounts(0, 0, 0, 0), False

    for item in mismatches:
        if not isinstance(item, dict):
            continue
        historical = item.get("historical_decision")
        replay = item.get("new_decision")
        if historical is None or replay is None:
            continue
        hist = bool(historical)
        repl = bool(replay)
        if hist and repl:
            tp += 1
        elif not hist and repl:
            fp += 1
        elif hist and not repl:
            fn += 1
        else:
            tn += 1

    partial = len(mismatches) > 0 or int(scorecard.get("total_evaluated", 0) or 0) > 0
    return ConfusionCounts(tp=tp, fp=fp, fn=fn, tn=tn), partial


def _display_enrichment(scorecard: Mapping[str, Any]) -> Mapping[str, Any]:
    display = scorecard.get("display")
    return display if isinstance(display, dict) else {}


def build_report(
    *,
    scorecard: Mapping[str, Any],
    tenant_id: str,
    since: str,
    until: str,
) -> BacktestReport:
    total_evaluated = int(scorecard.get("total_evaluated", 0) or 0)
    decision_match_count = int(scorecard.get("decision_match_count", 0) or 0)
    step_parity_count = int(scorecard.get("step_parity_count", 0) or 0)
    mismatches = scorecard.get("mismatches")
    mismatch_count = len(mismatches) if isinstance(mismatches, list) else 0

    display = _display_enrichment(scorecard)
    gt_raw = display.get("ground_truth_confusion")
    ground_truth = _parse_confusion(gt_raw) if isinstance(gt_raw, Mapping) else None

    replay_block = display.get("replay_predicted_block")
    replay_allow = display.get("replay_predicted_allow")
    replay_predicted_block = int(replay_block) if replay_block is not None else None
    replay_predicted_allow = int(replay_allow) if replay_allow is not None else None

    audit_reference, partial_audit = _audit_confusion_from_mismatches(scorecard)
    partial_note: str | None = None
    if partial_audit and mismatch_count < total_evaluated:
        partial_note = (
            "audit-reference confusion counts include divergent manifests only "
            f"({mismatch_count} mismatch rows); {decision_match_count} manifests had decision parity"
        )

    return BacktestReport(
        engine_label="tarka batch-replay (native CLI)",
        tenant_id=tenant_id,
        since=since,
        until=until,
        total_evaluated=total_evaluated,
        decision_match_count=decision_match_count,
        step_parity_count=step_parity_count,
        mismatch_count=mismatch_count,
        false_positive_rate_delta=float(scorecard.get("false_positive_rate_delta", 0.0) or 0.0),
        precision_delta=float(scorecard.get("precision_delta", 0.0) or 0.0),
        recall_delta=float(scorecard.get("recall_delta", 0.0) or 0.0),
        execution_time_ms=int(scorecard.get("execution_time_ms", 0) or 0),
        replay_predicted_block=replay_predicted_block,
        replay_predicted_allow=replay_predicted_allow,
        ground_truth=ground_truth,
        audit_reference=audit_reference if mismatch_count else None,
        partial_audit_note=partial_note,
    )


def print_report(report: BacktestReport) -> None:
    print()
    print(f"  Engine:                 {report.engine_label}")
    print(f"  Tenant / window:        {report.tenant_id}  [{report.since} .. {report.until}]")
    print(f"  Manifests evaluated:    {report.total_evaluated}")
    print(f"  Decision parity:        {report.decision_match_count}/{report.total_evaluated}")
    print(f"  Step parity:            {report.step_parity_count}/{report.total_evaluated}")
    print(f"  Manifest mismatches:    {report.mismatch_count}")
    print(f"  Execution time (ms):    {report.execution_time_ms}")
    print()
    print("  Replay scorecard deltas (batch-replay engine):")
    print(f"    false_positive_rate_delta: {report.false_positive_rate_delta:.6f}")
    print(f"    precision_delta:           {report.precision_delta:.6f}")
    print(f"    recall_delta:              {report.recall_delta:.6f}")
    print()

    if report.replay_predicted_block is not None and report.replay_predicted_allow is not None:
        _print_table(
            "  Prediction counts (replay engine: decision=True → BLOCK path)",
            [
                ("Metric", "Count", ""),
                ("Predicted BLOCK", str(report.replay_predicted_block), ""),
                ("Predicted ALLOW", str(report.replay_predicted_allow), ""),
            ],
        )
        print()

    if report.ground_truth is not None:
        gt = report.ground_truth
        _print_table(
            "  Ground truth × prediction (BLOCK = positive class)",
            [
                ("Actual / Pred", "Pred BLOCK", "Pred ALLOW"),
                ("Actual BLOCK", str(gt.tp), str(gt.fn)),
                ("Actual ALLOW", str(gt.fp), str(gt.tn)),
            ],
        )
        print()
        print(
            "  False positive rate (FP / (FP+TN)), ground-truth ALLOW only:  "
            f"{gt.false_positive_rate():.4f}"
        )
        print()
        return

    if report.audit_reference is not None and (
        report.audit_reference.tp
        or report.audit_reference.fp
        or report.audit_reference.fn
        or report.audit_reference.tn
    ):
        audit = report.audit_reference
        _print_table(
            "  Audit historical × replay prediction (BLOCK = positive class, mismatches only)",
            [
                ("Audit / Replay", "Replay BLOCK", "Replay ALLOW"),
                ("Audit BLOCK", str(audit.tp), str(audit.fn)),
                ("Audit ALLOW", str(audit.fp), str(audit.tn)),
            ],
        )
        print()
        print(
            "  False positive rate (FP / (FP+TN)), audit-ALLOW mismatches only:  "
            f"{audit.false_positive_rate():.4f}"
        )
        if report.partial_audit_note:
            print(f"  Note: {report.partial_audit_note}")
        print()
        return

    if report.total_evaluated == 0:
        print("  No manifests evaluated in the requested window.")
        print()
        return

    print(
        "  Per-class prediction tables require either ClickHouse ``normalized_labels`` "
        "(embedded in scorecard display) or divergent manifests in the scorecard mismatch list."
    )
    print(
        "  Embed optional counts under ``display`` when writing scorecard artifacts, e.g.:"
    )
    print('    {"display": {"replay_predicted_block": N, "replay_predicted_allow": M,')
    print('     "ground_truth_confusion": {"tp":..,"fp":..,"fn":..,"tn":..}}}')
    print()


def derive_window_from_parquet(
    parquet_path: Path,
    *,
    timestamp_column: str,
    limit: int | None,
) -> tuple[str, str]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("install duckdb to derive --since/--until from --parquet") from exc

    con = duckdb.connect(database=":memory:")
    limit_sql = f"LIMIT {int(limit)}" if limit is not None and limit > 0 else ""
    con.execute(
        f"""
        CREATE TABLE backtest_window_src AS
        SELECT * FROM read_parquet(?) {limit_sql}
        """,
        [str(parquet_path)],
    )
    cols = [row[0] for row in con.execute("DESCRIBE backtest_window_src").fetchall()]
    if timestamp_column not in cols:
        raise ValueError(
            f"timestamp column {timestamp_column!r} not in parquet columns: {cols}"
        )
    row = con.execute(
        f"""
        SELECT
            min(CAST("{timestamp_column}" AS TIMESTAMPTZ)),
            max(CAST("{timestamp_column}" AS TIMESTAMPTZ))
        FROM backtest_window_src
        """
    ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        raise ValueError("parquet window derivation produced empty bounds")

    since = row[0].isoformat().replace("+00:00", "Z")
    until = row[1].isoformat().replace("+00:00", "Z")
    return since, until


def run_batch_replay_subprocess(
    *,
    tarka_bin: str,
    tenant_id: str,
    since: str,
    until: str,
    scorecard_path: Path,
    clickhouse_url: str,
    clickhouse_database: str,
    clickhouse_table: str,
    clickhouse_user: str,
    clickhouse_password: str,
    registry_url: str | None,
    rule_json_path: Path | None,
    rule_content_id: str | None,
    wasm_dir: str | None,
    max_fpr_delta: float,
    concurrency: int | None,
    timeout_sec: float,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    cmd: list[str] = [
        tarka_bin,
        "batch-replay",
        "--since",
        since,
        "--until",
        until,
        "--tenant",
        tenant_id,
        "--scorecard-output",
        str(scorecard_path),
        "--clickhouse-url",
        clickhouse_url,
        "--clickhouse-database",
        clickhouse_database,
        "--clickhouse-table",
        clickhouse_table,
        "--clickhouse-user",
        clickhouse_user,
        "--max-false-positive-rate-delta",
        str(max_fpr_delta),
    ]
    if clickhouse_password:
        cmd.extend(["--clickhouse-password", clickhouse_password])
    if registry_url:
        cmd.extend(["--registry-url", registry_url])
    if rule_json_path is not None:
        cmd.extend(["--rule-json", str(rule_json_path)])
    if rule_content_id:
        cmd.extend(["--rule-content-id", rule_content_id])
    if wasm_dir:
        cmd.extend(["--wasm-dir", wasm_dir])
    if concurrency is not None and concurrency > 0:
        cmd.extend(["--concurrency", str(concurrency)])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if not scorecard_path.is_file():
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"batch-replay did not write scorecard ({detail})")

    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    if not isinstance(scorecard, dict):
        raise RuntimeError("scorecard JSON root must be an object")

    return scorecard, proc


def load_scorecard(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scorecard JSON root must be an object")
    return payload


def resolve_rule_artifacts(
    args: argparse.Namespace,
) -> tuple[Path | None, str | None, tempfile.TemporaryDirectory[str] | None]:
    if args.scorecard_input:
        return None, None, None

    if args.rule_json_file:
        rule_path = args.rule_json_file.expanduser().resolve()
        if not rule_path.is_file():
            raise FileNotFoundError(f"rule JSON not found: {rule_path}")
        rule_json = rule_path.read_text(encoding="utf-8")
        content_id = (args.rule_content_id or "").strip() or _rule_content_id_hex(rule_json)
        return rule_path, content_id, None

    if args.block_if_amount_gt is None:
        raise ValueError("provide --rule-json-file or --block-if-amount-gt")

    rule_json = _build_compare_amount_rule(threshold=float(args.block_if_amount_gt))
    tmp = tempfile.TemporaryDirectory(prefix="tarka_backtest_rule_")
    rule_path = Path(tmp.name) / "amount_gt_rule.json"
    rule_path.write_text(rule_json, encoding="utf-8")
    content_id = (args.rule_content_id or "").strip() or _rule_content_id_hex(rule_json)
    return rule_path, content_id, tmp


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", default=os.environ.get("TARKA_TENANT_ID", ""), help="ClickHouse tenant id")
    parser.add_argument("--since", default="", help="Inclusive RFC3339 window start")
    parser.add_argument("--until", default="", help="Inclusive RFC3339 window end")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=None,
        help="Optional Parquet used to derive --since/--until when bounds are omitted",
    )
    parser.add_argument(
        "--timestamp-column",
        default="event_time",
        help="Timestamp column for --parquet window derivation (default: event_time)",
    )
    parser.add_argument(
        "--parquet-limit",
        type=int,
        default=None,
        help="Optional row cap when scanning --parquet for window bounds",
    )
    parser.add_argument(
        "--scorecard-input",
        type=Path,
        default=None,
        help="Load an existing ReplayScorecard JSON instead of invoking batch-replay",
    )
    parser.add_argument(
        "--scorecard-output",
        type=Path,
        default=None,
        help="Keep batch-replay scorecard at this path (default: temp file)",
    )
    parser.add_argument("--tarka-bin", default=_default_tarka_bin(), help="tarka CLI binary (env TARKA_BIN)")
    parser.add_argument("--http-timeout", type=float, default=120.0, help="Subprocess timeout seconds")
    parser.add_argument(
        "--max-false-positive-rate-delta",
        type=float,
        default=1.0,
        help="Forwarded to batch-replay gate (default 1.0 for backtest tooling)",
    )
    parser.add_argument("--concurrency", type=int, default=None, help="batch-replay worker count")
    parser.add_argument("--clickhouse-url", default=os.environ.get("CLICKHOUSE_HTTP_URL", "http://127.0.0.1:8123"))
    parser.add_argument(
        "--clickhouse-database",
        default=os.environ.get("CLICKHOUSE_DATABASE", "tarka_audit"),
    )
    parser.add_argument(
        "--clickhouse-table",
        default=os.environ.get("CLICKHOUSE_TABLE", "evidence_manifests"),
    )
    parser.add_argument("--clickhouse-user", default=os.environ.get("CLICKHOUSE_USER", "default"))
    parser.add_argument("--clickhouse-password", default=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    parser.add_argument("--registry-url", default=os.environ.get("TARKA_REGISTRY_URL"))
    parser.add_argument("--rule-content-id", default=os.environ.get("TARKA_RULE_CONTENT_ID"))
    parser.add_argument("--wasm-dir", default=os.environ.get("TARKA_WASM_DIR"))
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit 1 when batch-replay returns non-zero (performance gate failure)",
    )

    rule_group = parser.add_mutually_exclusive_group()
    rule_group.add_argument("--rule-json-file", type=Path, help="RuleExpr JSON for --rule-json")
    rule_group.add_argument(
        "--block-if-amount-gt",
        type=float,
        nargs="?",
        const=5000.0,
        help="Write a compare_leaf rule: BLOCK when amount > threshold (default 5000)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    tenant_id = (args.tenant or "").strip()
    if not tenant_id:
        print("backtest_rules: --tenant is required (or set TARKA_TENANT_ID)", file=sys.stderr)
        return 1

    since = (args.since or "").strip()
    until = (args.until or "").strip()

    if args.parquet is not None:
        pq = args.parquet.expanduser().resolve()
        if not pq.is_file():
            print(f"backtest_rules: parquet not found: {pq}", file=sys.stderr)
            return 1
        if not since or not until:
            try:
                derived_since, derived_until = derive_window_from_parquet(
                    pq,
                    timestamp_column=str(args.timestamp_column),
                    limit=args.parquet_limit,
                )
            except (RuntimeError, ValueError) as exc:
                print(f"backtest_rules: {exc}", file=sys.stderr)
                return 1
            since = since or derived_since
            until = until or derived_until

    if not since or not until:
        print(
            "backtest_rules: --since and --until are required (or provide --parquet to derive them)",
            file=sys.stderr,
        )
        return 1

    rule_tmp: tempfile.TemporaryDirectory[str] | None = None
    try:
        rule_path, rule_content_id, rule_tmp = resolve_rule_artifacts(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"backtest_rules: {exc}", file=sys.stderr)
        return 1

    batch_proc: subprocess.CompletedProcess[str] | None = None

    try:
        if args.scorecard_input:
            scorecard = load_scorecard(args.scorecard_input.expanduser().resolve())
        else:
            out_path = args.scorecard_output
            if out_path is None:
                with tempfile.NamedTemporaryFile(
                    prefix="tarka_backtest_scorecard_",
                    suffix=".json",
                    delete=False,
                ) as tmp_scorecard:
                    out_path = Path(tmp_scorecard.name)

            scorecard, batch_proc = run_batch_replay_subprocess(
                tarka_bin=args.tarka_bin,
                tenant_id=tenant_id,
                since=since,
                until=until,
                scorecard_path=out_path.expanduser().resolve(),
                clickhouse_url=args.clickhouse_url,
                clickhouse_database=args.clickhouse_database,
                clickhouse_table=args.clickhouse_table,
                clickhouse_user=args.clickhouse_user,
                clickhouse_password=args.clickhouse_password,
                registry_url=args.registry_url,
                rule_json_path=rule_path,
                rule_content_id=rule_content_id,
                wasm_dir=args.wasm_dir,
                max_fpr_delta=args.max_false_positive_rate_delta,
                concurrency=args.concurrency,
                timeout_sec=args.http_timeout,
            )

            if batch_proc.returncode != 0:
                err = batch_proc.stderr.strip() or batch_proc.stdout.strip()
                if err:
                    print(err, file=sys.stderr)
                if args.fail_on_gate:
                    return 1
                print(
                    "backtest_rules: batch-replay exited non-zero; scorecard loaded for reporting",
                    file=sys.stderr,
                )
    except (RuntimeError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"backtest_rules: {exc}", file=sys.stderr)
        return 2
    finally:
        if rule_tmp is not None:
            rule_tmp.cleanup()

    report = build_report(
        scorecard=scorecard,
        tenant_id=tenant_id,
        since=since,
        until=until,
    )
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
