#!/usr/bin/env python3
"""
Run offline counter replay + optional Redis diff; write a JSON report (parity dashboard input).

Steps:
  1. Replay JSONL into scratch Redis (replay_aggregates.py logic inline-invoked via subprocess or import).
  2. Optionally diff scratch vs a reference Redis (diff_aggregate_redis.py).

Example::

    python scripts/replay/run_offline_parity.py \\
      --input scripts/replay/fixtures/parity_smoke.jsonl \\
      --scratch-url redis://localhost:6379/15 \\
      --reference-url redis://localhost:6379/0 \\
      --report /tmp/parity_report.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path, help="JSONL audit/export file")
    p.add_argument("--scratch-url", required=True, help="Scratch Redis URL")
    p.add_argument("--reference-url", default="", help="Optional prod/reference Redis for diff")
    p.add_argument("--pattern", default="fraud:agg*", help="Key pattern for diff")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--report", type=Path, default=None, help="Write JSON report path")
    p.add_argument("--agg-key-version", default="", help="Set AGG_KEY_VERSION for replay subprocess")
    args = p.parse_args()

    env = {**__import__("os").environ}
    if args.agg_key_version.strip():
        env["AGG_KEY_VERSION"] = args.agg_key_version.strip()

    replay_py = _REPO / "scripts" / "replay" / "replay_aggregates.py"
    cmd = [sys.executable, str(replay_py), "--input", str(args.input), "--redis-url", args.scratch_url]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    r = subprocess.run(cmd, cwd=str(_REPO), env=env, capture_output=True, text=True)
    replay_ok = r.returncode == 0
    replay_out = (r.stdout or "") + (r.stderr or "")

    diff_ok: bool | None = None
    diff_out = ""
    if args.reference_url:
        diff_py = _REPO / "scripts" / "replay" / "diff_aggregate_redis.py"
        dcmd = [
            sys.executable,
            str(diff_py),
            "--left-url",
            args.reference_url,
            "--right-url",
            args.scratch_url,
            "--pattern",
            args.pattern,
        ]
        dr = subprocess.run(dcmd, cwd=str(_REPO), capture_output=True, text=True)
        diff_ok = dr.returncode == 0
        diff_out = (dr.stdout or "") + (dr.stderr or "")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "scratch_redis_url": args.scratch_url,
        "reference_redis_url": args.reference_url or None,
        "agg_key_version": env.get("AGG_KEY_VERSION") or None,
        "replay": {"ok": replay_ok, "log": replay_out[-8000:]},
        "diff": None if not args.reference_url else {"ok": diff_ok, "log": diff_out[-8000:]},
    }
    text_report = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text_report, encoding="utf-8")
        print(f"wrote {args.report}")
    print(text_report)
    return 0 if replay_ok and (diff_ok is None or diff_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
