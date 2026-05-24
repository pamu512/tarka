#!/usr/bin/env python3
"""
Parity matrix validator: golden transaction batch vs V2 rule-engine evaluate and Rust batch-replay.

For each golden transaction the tool:

1. POSTs the envelope to ``POST /v1/evaluate`` (V2 rule-engine sidecar — the same evaluate path the
   orchestrator calls during ``POST /v1/ingest``).
2. Runs ``tarka batch-replay`` over the golden tenant/time window and loads the ``ReplayScorecard``.
3. Resolves the Rust replay decision per manifest (scorecard mismatches, then optional ``tarka replay``
   for manifests absent from the mismatch list).
4. Prints a per-row comparison matrix and exits non-zero on any Python↔Rust decision divergence.

Dry-run (``--dry-run``) uses ``expect`` / ``dry_run_*`` fields in the golden JSON for offline CI.

Example::

    python tools/verify_parity_matrix.py \\
      --golden tools/fixtures/parity_matrix_golden.json \\
      --evaluate-url http://127.0.0.1:8778 \\
      --tenant parity-demo

    python tools/verify_parity_matrix.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "parity_matrix_golden.json"
_FORENSIC_REPLAY_LINE = re.compile(
    r"^\s*replay\s*\(local engine\):\s*(true|false)\s*$",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return _REPO_ROOT


def _default_evaluate_url() -> str:
    return os.environ.get("RULE_ENGINE_URL", "http://127.0.0.1:8778").rstrip("/")


def _default_tarka_bin() -> str:
    explicit = os.environ.get("TARKA_BIN", "").strip()
    if explicit:
        return explicit
    found = shutil.which("tarka")
    if found:
        return found
    debug = _repo_root() / "target" / "debug" / "tarka"
    if debug.is_file():
        return str(debug)
    release = _repo_root() / "target" / "release" / "tarka"
    if release.is_file():
        return str(release)
    return "tarka"


def _short_uuid(value: str, width: int = 8) -> str:
    text = value.strip()
    if len(text) <= width:
        return text
    return f"{text[:width]}…"


def _fmt_bool(value: bool | None) -> str:
    if value is None:
        return "—"
    return "true" if value else "false"


def _fmt_actions(actions: Sequence[str] | None) -> str:
    if not actions:
        return "(none)"
    return ",".join(actions)


@dataclass(frozen=True)
class GoldenTransaction:
    label: str
    entity_id: str
    amount: float
    timestamp: str
    metadata: dict[str, Any]
    manifest_id: str | None
    expect_blocking: bool | None
    expect_actions: list[str] | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class GoldenBatch:
    schema_version: int
    description: str
    tenant_id: str
    since: str
    until: str
    transactions: list[GoldenTransaction]
    dry_run_scorecard: dict[str, Any] | None
    dry_run_rust_replay: dict[str, bool]


@dataclass
class PythonEvaluateOutcome:
    ok: bool
    status_code: int | None
    actions: list[str]
    blocking: bool
    blocking_rule_id: str | None
    trace_steps: int
    error: str | None = None


@dataclass
class RustReplayOutcome:
    replay_decision: bool | None
    historical_decision: bool | None
    batch_status: str
    diverged_rules: list[str] = field(default_factory=list)
    diff_trace: str = ""
    error: str | None = None
    source: str = ""


@dataclass
class ParityRow:
    golden: GoldenTransaction
    python: PythonEvaluateOutcome
    rust: RustReplayOutcome
    parity_ok: bool
    notes: list[str] = field(default_factory=list)


def load_golden_batch(path: Path) -> GoldenBatch:
    if not path.is_file():
        raise FileNotFoundError(f"golden batch not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("golden batch root must be a JSON object")

    schema_version = int(payload.get("schema_version", 0))
    if schema_version != 1:
        raise ValueError(f"unsupported schema_version {schema_version!r} (expected 1)")

    tenant_id = str(payload.get("tenant_id", "")).strip()
    since = str(payload.get("since", "")).strip()
    until = str(payload.get("until", "")).strip()
    if not tenant_id or not since or not until:
        raise ValueError("golden batch requires tenant_id, since, and until")

    raw_txns = payload.get("transactions")
    if not isinstance(raw_txns, list) or not raw_txns:
        raise ValueError("golden batch requires a non-empty transactions array")

    transactions: list[GoldenTransaction] = []
    for idx, raw in enumerate(raw_txns):
        if not isinstance(raw, dict):
            raise ValueError(f"transactions[{idx}] must be an object")
        label = str(raw.get("label", f"row_{idx}")).strip() or f"row_{idx}"
        entity_id = str(raw.get("entity_id", "")).strip()
        if not entity_id:
            raise ValueError(f"transactions[{idx}] missing entity_id")
        amount = raw.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError(f"transactions[{idx}] amount must be a positive number")
        timestamp = str(raw.get("timestamp", "")).strip()
        if not timestamp:
            raise ValueError(f"transactions[{idx}] missing timestamp")
        metadata = raw.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError(f"transactions[{idx}] metadata must be an object")
        manifest_raw = raw.get("manifest_id")
        manifest_id = str(manifest_raw).strip() if manifest_raw else None
        expect_raw = raw.get("expect")
        expect_blocking: bool | None = None
        expect_actions: list[str] | None = None
        if isinstance(expect_raw, dict):
            if "blocking" in expect_raw:
                expect_blocking = bool(expect_raw["blocking"])
            actions_raw = expect_raw.get("actions")
            if isinstance(actions_raw, list):
                expect_actions = [str(a) for a in actions_raw]

        transactions.append(
            GoldenTransaction(
                label=label,
                entity_id=entity_id,
                amount=float(amount),
                timestamp=timestamp,
                metadata=metadata,
                manifest_id=manifest_id,
                expect_blocking=expect_blocking,
                expect_actions=expect_actions,
                raw=raw,
            )
        )

    dry_run_scorecard = payload.get("dry_run_scorecard")
    if dry_run_scorecard is not None and not isinstance(dry_run_scorecard, dict):
        raise ValueError("dry_run_scorecard must be an object when present")

    dry_run_rust: dict[str, bool] = {}
    dry_run_raw = payload.get("dry_run_rust_replay")
    if isinstance(dry_run_raw, dict):
        for key, value in dry_run_raw.items():
            dry_run_rust[str(key).strip().lower()] = bool(value)

    return GoldenBatch(
        schema_version=schema_version,
        description=str(payload.get("description", "")),
        tenant_id=tenant_id,
        since=since,
        until=until,
        transactions=transactions,
        dry_run_scorecard=dry_run_scorecard,
        dry_run_rust_replay=dry_run_rust,
    )


def transaction_evaluate_body(txn: GoldenTransaction) -> dict[str, Any]:
    body: dict[str, Any] = {
        "entity_id": txn.entity_id,
        "amount": txn.amount,
        "timestamp": txn.timestamp,
        "metadata": txn.metadata,
    }
    country = txn.raw.get("country")
    if country is not None:
        body["country"] = str(country)
    return body


def python_decision_from_evaluate(body: Mapping[str, Any]) -> tuple[bool, list[str], str | None, int]:
    actions_raw = body.get("actions")
    actions: list[str] = []
    if isinstance(actions_raw, list):
        actions = [str(a) for a in actions_raw]
    blocking_rule_id = body.get("blocking_rule_id")
    blocking_rule_id_str = str(blocking_rule_id) if blocking_rule_id is not None else None
    blocking = blocking_rule_id_str is not None
    trace = body.get("evaluation_trace")
    trace_steps = len(trace) if isinstance(trace, list) else 0
    return blocking, actions, blocking_rule_id_str, trace_steps


def post_evaluate(evaluate_url: str, txn: GoldenTransaction, timeout_sec: float) -> PythonEvaluateOutcome:
    url = f"{evaluate_url.rstrip('/')}/v1/evaluate"
    payload = json.dumps(transaction_evaluate_body(txn)).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            status = int(getattr(response, "status", response.getcode()))
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return PythonEvaluateOutcome(
            ok=False,
            status_code=exc.code,
            actions=[],
            blocking=False,
            blocking_rule_id=None,
            trace_steps=0,
            error=f"HTTP {exc.code}: {detail[:500]}",
        )
    except urllib.error.URLError as exc:
        return PythonEvaluateOutcome(
            ok=False,
            status_code=None,
            actions=[],
            blocking=False,
            blocking_rule_id=None,
            trace_steps=0,
            error=f"request failed: {exc.reason}",
        )

    if status < 200 or status >= 300:
        return PythonEvaluateOutcome(
            ok=False,
            status_code=status,
            actions=[],
            blocking=False,
            blocking_rule_id=None,
            trace_steps=0,
            error=f"unexpected HTTP status {status}: {raw[:500]}",
        )

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        return PythonEvaluateOutcome(
            ok=False,
            status_code=status,
            actions=[],
            blocking=False,
            blocking_rule_id=None,
            trace_steps=0,
            error=f"invalid JSON response: {exc}",
        )

    if not isinstance(body, dict):
        return PythonEvaluateOutcome(
            ok=False,
            status_code=status,
            actions=[],
            blocking=False,
            blocking_rule_id=None,
            trace_steps=0,
            error="evaluate response must be a JSON object",
        )

    blocking, actions, blocking_rule_id, trace_steps = python_decision_from_evaluate(body)
    return PythonEvaluateOutcome(
        ok=True,
        status_code=status,
        actions=actions,
        blocking=blocking,
        blocking_rule_id=blocking_rule_id,
        trace_steps=trace_steps,
    )


def parse_forensic_replay_decision(stdout: str) -> bool | None:
    for line in stdout.splitlines():
        match = _FORENSIC_REPLAY_LINE.match(line)
        if match:
            return match.group(1).lower() == "true"
    return None


def run_subprocess(cmd: Sequence[str], *, timeout_sec: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


def run_batch_replay(
    *,
    tarka_bin: str,
    golden: GoldenBatch,
    scorecard_path: Path,
    clickhouse_url: str,
    clickhouse_database: str,
    clickhouse_table: str,
    clickhouse_user: str,
    clickhouse_password: str,
    registry_url: str | None,
    rule_json: str | None,
    rule_content_id: str | None,
    wasm_dir: str | None,
    max_fpr_delta: float,
    timeout_sec: float,
) -> tuple[dict[str, Any] | None, subprocess.CompletedProcess[str], str | None]:
    cmd: list[str] = [
        tarka_bin,
        "batch-replay",
        "--since",
        golden.since,
        "--until",
        golden.until,
        "--tenant",
        golden.tenant_id,
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
    if rule_json:
        cmd.extend(["--rule-json", rule_json])
    if rule_content_id:
        cmd.extend(["--rule-content-id", rule_content_id])
    if wasm_dir:
        cmd.extend(["--wasm-dir", wasm_dir])

    proc = run_subprocess(cmd, timeout_sec=timeout_sec)
    if not scorecard_path.is_file():
        err = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        return None, proc, f"scorecard not written ({err})"

    try:
        scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, proc, f"scorecard JSON parse error: {exc}"

    if not isinstance(scorecard, dict):
        return None, proc, "scorecard root must be a JSON object"

    return scorecard, proc, None


def run_forensic_replay(
    *,
    tarka_bin: str,
    manifest_id: str,
    clickhouse_url: str,
    clickhouse_database: str,
    clickhouse_table: str,
    clickhouse_user: str,
    clickhouse_password: str,
    registry_url: str | None,
    rule_json: str | None,
    rule_content_id: str | None,
    wasm_dir: str | None,
    timeout_sec: float,
) -> tuple[bool | None, str | None]:
    cmd: list[str] = [
        tarka_bin,
        "replay",
        manifest_id,
        "--clickhouse-url",
        clickhouse_url,
        "--clickhouse-database",
        clickhouse_database,
        "--clickhouse-table",
        clickhouse_table,
        "--clickhouse-user",
        clickhouse_user,
    ]
    if clickhouse_password:
        cmd.extend(["--clickhouse-password", clickhouse_password])
    if registry_url:
        cmd.extend(["--registry-url", registry_url])
    if rule_json:
        cmd.extend(["--rule-json", rule_json])
    if rule_content_id:
        cmd.extend(["--rule-content-id", rule_content_id])
    if wasm_dir:
        cmd.extend(["--wasm-dir", wasm_dir])

    proc = run_subprocess(cmd, timeout_sec=timeout_sec)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        return None, detail

    decision = parse_forensic_replay_decision(proc.stdout)
    if decision is None:
        return None, "could not parse replay (local engine) decision from forensic output"
    return decision, None


def index_scorecard_mismatches(scorecard: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    mismatches = scorecard.get("mismatches")
    if not isinstance(mismatches, list):
        return out
    for item in mismatches:
        if not isinstance(item, dict):
            continue
        manifest_id = str(item.get("manifest_id", "")).strip().lower()
        if manifest_id:
            out[manifest_id] = item
    return out


def resolve_rust_outcome(
    *,
    txn: GoldenTransaction,
    mismatch_index: Mapping[str, Mapping[str, Any]],
    golden: GoldenBatch,
    dry_run: bool,
    resolve_forensic: bool,
    tarka_bin: str,
    clickhouse_url: str,
    clickhouse_database: str,
    clickhouse_table: str,
    clickhouse_user: str,
    clickhouse_password: str,
    registry_url: str | None,
    rule_json: str | None,
    rule_content_id: str | None,
    wasm_dir: str | None,
    timeout_sec: float,
) -> RustReplayOutcome:
    if not txn.manifest_id:
        return RustReplayOutcome(
            replay_decision=None,
            historical_decision=None,
            batch_status="NO_MANIFEST",
            error="golden row has no manifest_id",
            source="n/a",
        )

    manifest_key = txn.manifest_id.strip().lower()

    if dry_run:
        replay = golden.dry_run_rust_replay.get(manifest_key)
        if replay is None:
            return RustReplayOutcome(
                replay_decision=None,
                historical_decision=None,
                batch_status="DRY_RUN_MISSING",
                error=f"dry_run_rust_replay missing key {txn.manifest_id}",
                source="dry_run",
            )
        return RustReplayOutcome(
            replay_decision=replay,
            historical_decision=replay,
            batch_status="DRY_RUN",
            source="dry_run",
        )

    mismatch = mismatch_index.get(manifest_key)
    if mismatch is not None:
        historical = mismatch.get("historical_decision")
        new_decision = mismatch.get("new_decision")
        diverged_raw = mismatch.get("diverged_rules")
        diverged = [str(x) for x in diverged_raw] if isinstance(diverged_raw, list) else []
        diff_trace = str(mismatch.get("diff_trace", ""))
        err = mismatch.get("error")
        hist_bool = bool(historical) if historical is not None else None
        new_bool = bool(new_decision) if new_decision is not None else None
        return RustReplayOutcome(
            replay_decision=new_bool,
            historical_decision=hist_bool,
            batch_status="MISMATCH",
            diverged_rules=diverged,
            diff_trace=diff_trace,
            error=str(err) if err is not None else None,
            source="batch_scorecard",
        )

    if not resolve_forensic:
        return RustReplayOutcome(
            replay_decision=None,
            historical_decision=None,
            batch_status="BATCH_OK",
            source="batch_scorecard",
            error="rust replay decision unresolved (use --resolve-forensic or enable default)",
        )

    replay_decision, err = run_forensic_replay(
        tarka_bin=tarka_bin,
        manifest_id=txn.manifest_id,
        clickhouse_url=clickhouse_url,
        clickhouse_database=clickhouse_database,
        clickhouse_table=clickhouse_table,
        clickhouse_user=clickhouse_user,
        clickhouse_password=clickhouse_password,
        registry_url=registry_url,
        rule_json=rule_json,
        rule_content_id=rule_content_id,
        wasm_dir=wasm_dir,
        timeout_sec=timeout_sec,
    )
    if err is not None:
        return RustReplayOutcome(
            replay_decision=None,
            historical_decision=None,
            batch_status="FORENSIC_ERROR",
            error=err,
            source="forensic_replay",
        )

    return RustReplayOutcome(
        replay_decision=replay_decision,
        historical_decision=None,
        batch_status="BATCH_OK",
        source="forensic_replay",
    )


def evaluate_row_parity(
    txn: GoldenTransaction,
    python: PythonEvaluateOutcome,
    rust: RustReplayOutcome,
) -> tuple[bool, list[str]]:
    notes: list[str] = []

    if not python.ok:
        return False, [python.error or "python evaluate failed"]

    if txn.expect_blocking is not None and python.blocking != txn.expect_blocking:
        notes.append(
            f"python blocking {python.blocking} != golden expect.blocking {txn.expect_blocking}"
        )
    if txn.expect_actions is not None and python.actions != txn.expect_actions:
        notes.append(
            f"python actions {python.actions!r} != golden expect.actions {txn.expect_actions!r}"
        )

    if rust.replay_decision is None:
        notes.append(rust.error or "rust replay decision unavailable")
        return False, notes

    if python.blocking != rust.replay_decision:
        notes.append(
            f"python blocking {_fmt_bool(python.blocking)} != rust replay {_fmt_bool(rust.replay_decision)}"
        )
        return False, notes

    if rust.batch_status == "MISMATCH":
        notes.append("manifest listed in batch-replay mismatches (historical vs replay diverged in CH audit)")

    return True, notes


def print_matrix(
    *,
    golden_path: Path,
    evaluate_url: str,
    golden: GoldenBatch,
    rows: Sequence[ParityRow],
    scorecard: Mapping[str, Any] | None,
    batch_proc: subprocess.CompletedProcess[str] | None,
    dry_run: bool,
) -> None:
    width = 96
    print("=" * width)
    print(" Tarka V2 Parity Matrix — Python POST /v1/evaluate  vs  Rust batch-replay")
    print("=" * width)
    print(f"Golden batch : {golden_path}")
    print(f"Tenant/window: {golden.tenant_id}  [{golden.since} .. {golden.until}]")
    print(f"Evaluate URL : {evaluate_url}/v1/evaluate")
    print(f"Mode         : {'dry-run' if dry_run else 'live'}")
    print()

    headers = (
        "label",
        "entity_id",
        "py_block",
        "py_actions",
        "rust_replay",
        "rust_hist",
        "batch",
        "PARITY",
    )
    col_widths = (18, 10, 9, 16, 11, 9, 12, 6)
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths, strict=True))
    print("--- Per-transaction matrix ---")
    print(header_line)
    print("-+-".join("-" * w for w in col_widths))

    pass_count = 0
    for row in rows:
        parity_label = "OK" if row.parity_ok else "FAIL"
        if row.parity_ok:
            pass_count += 1
        cells = (
            row.golden.label[: col_widths[0]],
            _short_uuid(row.golden.entity_id, 8).ljust(col_widths[1]),
            _fmt_bool(row.python.blocking).ljust(col_widths[2]),
            _fmt_actions(row.python.actions)[: col_widths[3]].ljust(col_widths[3]),
            _fmt_bool(row.rust.replay_decision).ljust(col_widths[4]),
            _fmt_bool(row.rust.historical_decision).ljust(col_widths[5]),
            row.rust.batch_status[: col_widths[6]].ljust(col_widths[6]),
            parity_label.ljust(col_widths[7]),
        )
        print(" | ".join(cells))
        for note in row.notes:
            print(f"  ↳ {note}")
        if row.rust.diverged_rules:
            print(f"  ↳ diverged_rules: {', '.join(row.rust.diverged_rules)}")
        if row.rust.diff_trace.strip():
            first_line = row.rust.diff_trace.strip().splitlines()[0]
            print(f"  ↳ diff: {first_line[:120]}")

    print()
    print("--- Batch scorecard summary ---")
    if scorecard is None:
        print(" (no scorecard loaded)")
    else:
        print(f" total_evaluated         : {scorecard.get('total_evaluated')}")
        print(f" decision_match_count    : {scorecard.get('decision_match_count')}")
        print(f" step_parity_count       : {scorecard.get('step_parity_count')}")
        mismatches = scorecard.get("mismatches")
        mismatch_count = len(mismatches) if isinstance(mismatches, list) else "?"
        print(f" mismatches              : {mismatch_count}")
        print(f" false_positive_rate_delta: {scorecard.get('false_positive_rate_delta')}")
        print(f" execution_time_ms       : {scorecard.get('execution_time_ms')}")

    if batch_proc is not None and not dry_run:
        print()
        print("--- batch-replay subprocess ---")
        print(f" exit_code: {batch_proc.returncode}")
        if batch_proc.stderr.strip():
            stderr_preview = batch_proc.stderr.strip().splitlines()[-3:]
            for line in stderr_preview:
                print(f" stderr: {line}")

    print()
    print("--- Verdict ---")
    total = len(rows)
    if pass_count == total:
        print(f" ALL ROWS PASS ({pass_count}/{total})")
    else:
        print(f" PARITY FAILURES ({pass_count}/{total} passed, {total - pass_count} failed)")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=_DEFAULT_GOLDEN,
        help=f"Golden batch JSON (default: {_DEFAULT_GOLDEN})",
    )
    parser.add_argument(
        "--evaluate-url",
        default=_default_evaluate_url(),
        help="Rule-engine base URL (env RULE_ENGINE_URL)",
    )
    parser.add_argument(
        "--tarka-bin",
        default=_default_tarka_bin(),
        help="Path to tarka CLI (env TARKA_BIN)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use expect/dry_run_* fields from golden JSON (no network/subprocess)",
    )
    parser.add_argument(
        "--skip-batch-replay",
        action="store_true",
        help="Skip batch-replay (still resolves rust via dry_run or forensic replay)",
    )
    parser.add_argument(
        "--no-resolve-forensic",
        action="store_true",
        help="Do not run `tarka replay` for manifests absent from scorecard mismatches",
    )
    parser.add_argument("--http-timeout", type=float, default=45.0, help="HTTP/subprocess timeout seconds")
    parser.add_argument(
        "--max-false-positive-rate-delta",
        type=float,
        default=1.0,
        help="Forwarded to batch-replay performance gate (default 1.0 for parity tooling)",
    )
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
    parser.add_argument("--rule-json", default=os.environ.get("TARKA_RULE_JSON"))
    parser.add_argument("--rule-content-id", default=os.environ.get("TARKA_RULE_CONTENT_ID"))
    parser.add_argument("--wasm-dir", default=os.environ.get("TARKA_WASM_DIR"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    golden_path: Path = args.golden.expanduser().resolve()

    try:
        golden = load_golden_batch(golden_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_parity_matrix: golden load failed: {exc}", file=sys.stderr)
        return 2

    scorecard: dict[str, Any] | None = None
    batch_proc: subprocess.CompletedProcess[str] | None = None
    mismatch_index: dict[str, dict[str, Any]] = {}

    if args.dry_run:
        scorecard = golden.dry_run_scorecard
        if scorecard is None:
            print("verify_parity_matrix: dry-run requires dry_run_scorecard in golden JSON", file=sys.stderr)
            return 2
        mismatch_index = index_scorecard_mismatches(scorecard)
    elif not args.skip_batch_replay:
        with tempfile.TemporaryDirectory(prefix="tarka_parity_") as tmp:
            scorecard_path = Path(tmp) / "scorecard.json"
            scorecard, batch_proc, err = run_batch_replay(
                tarka_bin=args.tarka_bin,
                golden=golden,
                scorecard_path=scorecard_path,
                clickhouse_url=args.clickhouse_url,
                clickhouse_database=args.clickhouse_database,
                clickhouse_table=args.clickhouse_table,
                clickhouse_user=args.clickhouse_user,
                clickhouse_password=args.clickhouse_password,
                registry_url=args.registry_url,
                rule_json=args.rule_json,
                rule_content_id=args.rule_content_id,
                wasm_dir=args.wasm_dir,
                max_fpr_delta=args.max_false_positive_rate_delta,
                timeout_sec=args.http_timeout,
            )
            if err is not None:
                print(f"verify_parity_matrix: batch-replay failed: {err}", file=sys.stderr)
                if batch_proc is not None and batch_proc.stderr.strip():
                    print(batch_proc.stderr.strip(), file=sys.stderr)
                return 2
            mismatch_index = index_scorecard_mismatches(scorecard or {})

    rows: list[ParityRow] = []
    for txn in golden.transactions:
        if args.dry_run:
            if txn.expect_blocking is None:
                python = PythonEvaluateOutcome(
                    ok=False,
                    status_code=None,
                    actions=[],
                    blocking=False,
                    blocking_rule_id=None,
                    trace_steps=0,
                    error="dry-run requires expect.blocking on each transaction",
                )
            else:
                python = PythonEvaluateOutcome(
                    ok=True,
                    status_code=200,
                    actions=list(txn.expect_actions or []),
                    blocking=bool(txn.expect_blocking),
                    blocking_rule_id="dry-run" if txn.expect_blocking else None,
                    trace_steps=0,
                )
        else:
            python = post_evaluate(args.evaluate_url, txn, timeout_sec=args.http_timeout)

        rust = resolve_rust_outcome(
            txn=txn,
            mismatch_index=mismatch_index,
            golden=golden,
            dry_run=args.dry_run,
            resolve_forensic=not args.no_resolve_forensic,
            tarka_bin=args.tarka_bin,
            clickhouse_url=args.clickhouse_url,
            clickhouse_database=args.clickhouse_database,
            clickhouse_table=args.clickhouse_table,
            clickhouse_user=args.clickhouse_user,
            clickhouse_password=args.clickhouse_password,
            registry_url=args.registry_url,
            rule_json=args.rule_json,
            rule_content_id=args.rule_content_id,
            wasm_dir=args.wasm_dir,
            timeout_sec=args.http_timeout,
        )

        parity_ok, notes = evaluate_row_parity(txn, python, rust)
        rows.append(
            ParityRow(
                golden=txn,
                python=python,
                rust=rust,
                parity_ok=parity_ok,
                notes=notes,
            )
        )

    print_matrix(
        golden_path=golden_path,
        evaluate_url=args.evaluate_url,
        golden=golden,
        rows=rows,
        scorecard=scorecard,
        batch_proc=batch_proc,
        dry_run=args.dry_run,
    )

    return 0 if all(row.parity_ok for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
