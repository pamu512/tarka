#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

"""
One-command audit-shaped offline parity:

  audit payload_snapshot JSONL → replay JSONL → scratch Redis → optional reference diff.

Modes:
  --mode fixture  (default) use fixtures/audit_payload_snapshot.jsonl
  --mode file     --audit-input PATH (same shape)
  --mode export   export_audit_to_jsonl from DATABASE_URL then convert is skipped
                  (export already emits replay shape) → run_offline_parity
"""

_REPO = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_DEFAULT_AUDIT = _HERE / "fixtures" / "audit_payload_snapshot.jsonl"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit-shaped offline counter parity")
    p.add_argument(
        "--mode",
        choices=("fixture", "file", "export"),
        default="fixture",
    )
    p.add_argument("--audit-input", type=Path, default=None, help="For --mode file")
    p.add_argument("--tenant-id", default="", help="For --mode export")
    p.add_argument("--entity-id", default="", help="For --mode export")
    p.add_argument("--export-limit", type=int, default=5000)
    p.add_argument("--scratch-url", required=True)
    p.add_argument("--reference-url", default="")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--agg-key-version", default="")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="tarka-audit-parity-") as tmp:
        tmp_path = Path(tmp)
        replay_jsonl = tmp_path / "replay.jsonl"

        if args.mode == "export":
            if not args.tenant_id.strip() or not args.entity_id.strip():
                print("--mode export requires --tenant-id and --entity-id", file=sys.stderr)
                return 2
            export_py = _HERE / "export_audit_to_jsonl.py"
            # export already writes replay-shaped rows
            er = subprocess.run(
                [
                    sys.executable,
                    str(export_py),
                    "--tenant-id",
                    args.tenant_id.strip(),
                    "--entity-id",
                    args.entity_id.strip(),
                    "--out",
                    str(replay_jsonl),
                    "--limit",
                    str(args.export_limit),
                ],
                cwd=str(_REPO),
            )
            if er.returncode != 0:
                return er.returncode
        else:
            audit_src = (
                _DEFAULT_AUDIT
                if args.mode == "fixture"
                else args.audit_input
            )
            if audit_src is None:
                print("--mode file requires --audit-input", file=sys.stderr)
                return 2
            if not audit_src.is_file():
                print(f"missing audit fixture: {audit_src}", file=sys.stderr)
                return 2
            convert_py = _HERE / "audit_snapshot_to_replay.py"
            cr = subprocess.run(
                [
                    sys.executable,
                    str(convert_py),
                    "--input",
                    str(audit_src),
                    "--out",
                    str(replay_jsonl),
                ],
                cwd=str(_REPO),
            )
            if cr.returncode != 0:
                return cr.returncode

        parity_py = _HERE / "run_offline_parity.py"
        cmd = [
            sys.executable,
            str(parity_py),
            "--input",
            str(replay_jsonl),
            "--scratch-url",
            args.scratch_url,
            "--report",
            str(args.report),
        ]
        if args.reference_url:
            cmd.extend(["--reference-url", args.reference_url])
        if args.agg_key_version.strip():
            cmd.extend(["--agg-key-version", args.agg_key_version.strip()])
        if args.limit is not None:
            cmd.extend(["--limit", str(args.limit)])
        return subprocess.run(cmd, cwd=str(_REPO)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
