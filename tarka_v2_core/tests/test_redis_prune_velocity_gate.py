"""Gate: ``prune_velocity.lua`` uses SCAN (not KEYS) and prunes idle velocity keys without touching sessions."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LUA_PATH = _REPO_ROOT / "scripts" / "redis" / "prune_velocity.lua"


def test_lua_uses_scan_not_keys() -> None:
    src = _LUA_PATH.read_text(encoding="utf-8")
    assert re.search(r'redis\.call\s*\(\s*["\']SCAN["\']', src), "script must call SCAN"
    assert not re.search(
        r'redis\.call\s*\(\s*["\']KEYS["\']',
        src,
    ), "script must not call KEYS (blocks Redis event loop)"
    assert re.search(r'redis\.call\s*\(\s*["\']OBJECT["\']', src), "script must call OBJECT IDLETIME path"


def test_prune_drops_idle_velocity_preserves_session_key() -> None:
    """
    Live Redis gate (optional): ``REDIS_PRUNE_GATE_URL`` (e.g. ``redis://127.0.0.1:6379/15``).

    Seeds a ``velocity:*`` key and a ``session:*`` key; after a short idle, runs the script with a
    **1-second** threshold so CI does not wait 24h; asserts velocity key is gone and session remains.
    """
    url = (os.environ.get("REDIS_PRUNE_GATE_URL") or "").strip()
    if not url:
        pytest.skip("Set REDIS_PRUNE_GATE_URL to run live Redis prune gate (e.g. redis://127.0.0.1:6379/15)")

    try:
        import redis
    except ImportError:
        pytest.skip("redis-py not installed")

    script = _LUA_PATH.read_text(encoding="utf-8")
    r = redis.Redis.from_url(url, decode_responses=True)
    try:
        r.flushdb()
        r.set("velocity:gate:prune_me", "1")
        r.set("session:gate:keep_me", "active")

        time.sleep(1.6)

        sha = r.script_load(script)
        res = r.evalsha(sha, 0, "velocity:*", "1", "500", "100", "0")
        cursor = str(res[0])
        assert cursor == "0"
        assert int(res[1]) >= 1

        assert r.get("velocity:gate:prune_me") is None
        assert r.get("session:gate:keep_me") == "active"
    finally:
        r.flushdb()
        r.close()
