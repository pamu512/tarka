#!/usr/bin/env python3
"""
Run ``prune_velocity.lua`` in chunks until SCAN cursor returns ``0``.

Example::

    export REDIS_URL=redis://127.0.0.1:6379/0
    python scripts/redis/run_prune_velocity.py --pattern 'velocity:*'
    python scripts/redis/run_prune_velocity.py --pattern 'anumana:velocity:*'

Uses **EVAL** + returned cursor (Lua uses **SCAN**, never **KEYS**).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _insert_deploy_settings_path() -> None:
    """Allow ``pip install -e``-free runs from a git checkout."""
    pkg_src = _repo_root() / "packages" / "tarka-deploy-settings" / "src"
    if pkg_src.is_dir():
        roots = sys.path
        sp = str(pkg_src)
        if sp not in roots:
            sys.path.insert(0, sp)


def _default_idle_sec() -> int:
    """
    Prune window comes from env / validated settings — never a hardcoded day-bound default in this
    script (enterprise Redis velocity policy differs from Neo4j AML retention).
    """
    for key in ("REDIS_VELOCITY_PRUNE_IDLE_SEC", "REDIS_VELOCITY_TTL"):
        raw = (os.environ.get(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    _insert_deploy_settings_path()
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().redis_velocity_prune_idle_sec
    except Exception as exc:
        print(
            "Configure prune idle threshold: set REDIS_VELOCITY_PRUNE_IDLE_SEC or REDIS_VELOCITY_TTL, "
            "or install packages/tarka-deploy-settings and set TARKA_DEPLOY_PROFILE — "
            "see deploy/env/runtime-demo.env.example.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def main() -> int:
    try:
        import redis
    except ImportError:
        print("Install redis-py: pip install 'redis[hiredis]'", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Chunked velocity key prune (SCAN + OBJECT IDLETIME).")
    parser.add_argument(
        "--url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        help="Redis URL (default REDIS_URL or redis://127.0.0.1:6379/0)",
    )
    parser.add_argument(
        "--pattern",
        default="velocity:*",
        help="SCAN MATCH glob (default velocity:*). Also try anumana:velocity:*",
    )
    parser.add_argument(
        "--idle-sec",
        type=int,
        default=None,
        help="Delete keys with OBJECT IDLETIME >= this many seconds (default: env / Pydantic settings)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=200,
        help="Max SCAN rounds per EVAL (default 200)",
    )
    parser.add_argument(
        "--scan-count",
        type=int,
        default=100,
        help="SCAN COUNT hint (default 100)",
    )
    parser.add_argument(
        "--lua",
        type=Path,
        default=_repo_root() / "scripts" / "redis" / "prune_velocity.lua",
        help="Path to prune_velocity.lua",
    )
    args = parser.parse_args()
    idle_sec = args.idle_sec if args.idle_sec is not None else _default_idle_sec()

    script = args.lua.read_text(encoding="utf-8")
    client = redis.Redis.from_url(args.url, decode_responses=True)
    sha = client.script_load(script)

    cursor = "0"
    total_deleted = 0
    total_examined = 0
    invocations = 0
    try:
        while True:
            invocations += 1
            res = client.evalsha(
                sha,
                0,
                args.pattern,
                str(idle_sec),
                str(args.max_rounds),
                str(args.scan_count),
                str(cursor),
            )
            cursor = str(res[0])
            total_deleted += int(res[1])
            total_examined += int(res[2])
            if cursor in ("0", "None"):
                break
        print(
            f"prune_velocity_done invocations={invocations} deleted={total_deleted} examined={total_examined}",
            file=sys.stderr,
        )
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
