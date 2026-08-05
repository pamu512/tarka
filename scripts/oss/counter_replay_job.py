#!/usr/bin/env python3
"""Wave 5: counter replay job surface — emit pass/fail artifact.

Modes:
  --dry-run  validate fixture JSONL shape + write artifact (no Redis)
  default    dual-replay into scratch Redis DBs + diff (needs Redis + redis pkg)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURE = _REPO / "scripts" / "replay" / "fixtures" / "parity_smoke.jsonl"
_DEFAULT_REPORT = _REPO / "artifacts" / "counter-replay-job.json"


def _validate_fixture(path: Path) -> dict:
    if not path.is_file():
        return {"ok": False, "error": f"missing fixture {path}"}
    n = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"line {i}: {e}"}
        if not isinstance(row, dict):
            return {"ok": False, "error": f"line {i}: expected object"}
        n += 1
    if n < 1:
        return {"ok": False, "error": "fixture empty"}
    return {"ok": True, "events": n, "fixture": str(path.relative_to(_REPO))}


def _base_redis_url(url: str) -> str:
    """Strip trailing /db index so we can attach /14 and /15."""
    u = url.rstrip("/")
    # redis://host:6379/0 → redis://host:6379
    if u.rsplit("/", 1)[-1].isdigit() and u.count("/") >= 3:
        return u.rsplit("/", 1)[0]
    return u


def _run_redis_parity(fixture: Path, redis_url: str) -> dict:
    env = {**os.environ, "AGG_KEY_VERSION": os.environ.get("AGG_KEY_VERSION") or "wave5_job_v1"}
    try:
        import redis  # type: ignore
    except ImportError:
        return {"ok": False, "error": "redis package not installed"}

    base = _base_redis_url(redis_url)
    left_url = f"{base}/14"
    right_url = f"{base}/15"

    for db_url in (left_url, right_url):
        r = redis.from_url(db_url, decode_responses=True)
        r.flushdb()
        r.close()

    replay = _REPO / "scripts" / "replay" / "replay_aggregates.py"
    for db_url in (left_url, right_url):
        proc = subprocess.run(
            [
                sys.executable,
                str(replay),
                "--input",
                str(fixture),
                "--redis-url",
                db_url,
            ],
            cwd=str(_REPO),
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": "replay failed",
                "stderr": (proc.stderr or "")[-2000:],
            }

    diff = _REPO / "scripts" / "replay" / "diff_aggregate_redis.py"
    dproc = subprocess.run(
        [
            sys.executable,
            str(diff),
            "--left-url",
            left_url,
            "--right-url",
            right_url,
            "--pattern",
            "fraud:agg*",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    return {
        "ok": dproc.returncode == 0,
        "mode": "redis_dual_diff",
        "left_url": left_url,
        "right_url": right_url,
        "diff_exit": dproc.returncode,
        "diff_out": ((dproc.stdout or "") + (dproc.stderr or ""))[-2000:],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=_DEFAULT_FIXTURE)
    p.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate fixture only (no Redis); still writes artifact",
    )
    p.add_argument(
        "--redis-url",
        default=os.environ.get("COUNTER_REPLAY_REDIS_URL", "redis://127.0.0.1:6379"),
    )
    args = p.parse_args()

    fixture_meta = _validate_fixture(args.input)
    if not fixture_meta.get("ok"):
        report = {
            "schema_id": "tarka.counter_replay_job/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "ok": False,
            "mode": "fixture_validate",
            **fixture_meta,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    if args.dry_run:
        report = {
            "schema_id": "tarka.counter_replay_job/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "ok": True,
            "mode": "dry_run",
            **fixture_meta,
            "hint": "Re-run without --dry-run with Redis for dual-diff parity",
        }
    else:
        parity = _run_redis_parity(args.input, args.redis_url)
        report = {
            "schema_id": "tarka.counter_replay_job/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "events": fixture_meta.get("events"),
            "fixture": fixture_meta.get("fixture"),
            **parity,
            "ok": bool(parity.get("ok")),
        }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {args.report}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
