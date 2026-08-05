#!/usr/bin/env python3
"""Critical L1 counter parity — dual-diff artifact (Redis hash vs process/file counters).

Modes:
  dry_run   validate fixture + write artifact; matched is always False (not ops proof)
  dual_diff replay fixture, diff Redis ZSETs + process compute_features vs golden file

Produces rules/counter_parity_last.json:
  {schema_id, ts, mode, matched, diffs, ...}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
_SHARED = _REPO / "services" / "shared"
_DEFAULT_FIXTURE = _REPO / "scripts" / "replay" / "fixtures" / "parity_smoke.jsonl"
_DEFAULT_GOLDEN = _REPO / "scripts" / "replay" / "fixtures" / "parity_smoke_counters.json"
_DEFAULT_OUT = _REPO / "rules" / "counter_parity_last.json"
SCHEMA_ID = "tarka.counter_parity/v1"

try:
    import redis as redis_sync
except ImportError:
    redis_sync = None  # type: ignore[assignment,misc]


def _ensure_paths() -> None:
    for p in (_SHARED, _REPO / "services" / "decision-api" / "src"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def _validate_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "error": f"missing fixture {path}"}
    n = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"line {i}: {exc}"}
        if not isinstance(row, dict):
            return {"ok": False, "error": f"line {i}: expected object"}
        n += 1
    if n < 1:
        return {"ok": False, "error": "fixture empty"}
    return {"ok": True, "events": n, "fixture": str(path.relative_to(_REPO))}


def _load_golden(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"missing golden counters file {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("golden counters must be a JSON object")
    return data


def _compare_counter_maps(
    *,
    tenant_id: str,
    entity_id: str,
    process: dict[str, Any],
    expected: dict[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    keys = sorted(set(process) | set(expected))
    for key in keys:
        pv, ev = process.get(key), expected.get(key)
        if pv is None or ev is None:
            diffs.append(
                {
                    "kind": "counter_missing",
                    "source": source,
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "key": key,
                    "process": pv,
                    "expected": ev,
                }
            )
            continue
        try:
            pf, ef = float(pv), float(ev)
        except (TypeError, ValueError):
            if pv != ev:
                diffs.append(
                    {
                        "kind": "counter_mismatch",
                        "source": source,
                        "tenant_id": tenant_id,
                        "entity_id": entity_id,
                        "key": key,
                        "process": pv,
                        "expected": ev,
                    }
                )
            continue
        if abs(pf - ef) > 1e-9:
            diffs.append(
                {
                    "kind": "counter_mismatch",
                    "source": source,
                    "tenant_id": tenant_id,
                    "entity_id": entity_id,
                    "key": key,
                    "process": pf,
                    "expected": ef,
                }
            )
    return diffs


def _base_redis_url(url: str) -> str:
    u = url.rstrip("/")
    if u.rsplit("/", 1)[-1].isdigit() and u.count("/") >= 3:
        return u.rsplit("/", 1)[0]
    return u


def _redis_zset_diffs(left_url: str, right_url: str, pattern: str) -> list[dict[str, Any]]:
    diff_py = _REPO / "scripts" / "replay" / "diff_aggregate_redis.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(diff_py),
            "--left-url",
            left_url,
            "--right-url",
            right_url,
            "--pattern",
            pattern,
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return []
    out = (proc.stdout or "") + (proc.stderr or "")
    return [{"kind": "redis_zset_mismatch", "detail": out.strip()[-2000:]}]


def _flush_redis_dbs(*db_urls: str) -> None:
    if redis_sync is None:
        raise RuntimeError("redis package not installed")
    for db_url in db_urls:
        r = redis_sync.from_url(db_url, decode_responses=True)
        r.flushdb()
        r.close()


def _run_redis_replay(fixture: Path, redis_url: str, agg_key_version: str) -> None:
    replay = _REPO / "scripts" / "replay" / "replay_aggregates.py"
    env = {**os.environ, "AGG_KEY_VERSION": agg_key_version}
    proc = subprocess.run(
        [
            sys.executable,
            str(replay),
            "--input",
            str(fixture),
            "--redis-url",
            redis_url,
        ],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "replay failed")[-2000:])


async def _compute_process_counters(
    redis_url: str,
    golden: dict[str, Any],
    *,
    agg_key_version: str,
) -> dict[str, dict[str, Any]]:
    _ensure_paths()
    import redis.asyncio as aioredis
    from fraud_aggregates import AggregateStore

    os.environ["AGG_KEY_VERSION"] = agg_key_version
    clock_at = float(golden.get("clock_at") or 0.0)
    tenant_id = str(golden.get("tenant_id") or "")
    entities = golden.get("entities") or {}
    if not tenant_id or not isinstance(entities, dict):
        raise ValueError("golden file needs tenant_id and entities")

    client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        store = AggregateStore(client, clock=lambda: clock_at)
        out: dict[str, dict[str, Any]] = {}
        for entity_id, spec in entities.items():
            if not isinstance(spec, dict):
                continue
            payload = dict(spec.get("payload_fields") or {})
            out[str(entity_id)] = await store.compute_features(tenant_id, str(entity_id), payload)
        return out
    finally:
        await client.aclose()


def _compare_process_vs_file(
    process_by_entity: dict[str, dict[str, Any]],
    golden: dict[str, Any],
) -> list[dict[str, Any]]:
    tenant_id = str(golden.get("tenant_id") or "")
    entities = golden.get("entities") or {}
    diffs: list[dict[str, Any]] = []
    if not isinstance(entities, dict):
        return [{"kind": "golden_invalid", "detail": "entities must be object"}]
    for entity_id, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        expected = spec.get("counters") or {}
        if not isinstance(expected, dict):
            diffs.append({"kind": "golden_invalid", "entity_id": str(entity_id)})
            continue
        process = process_by_entity.get(str(entity_id), {})
        diffs.extend(
            _compare_counter_maps(
                tenant_id=tenant_id,
                entity_id=str(entity_id),
                process=process,
                expected=expected,
                source="file",
            )
        )
    return diffs


def run(
    *,
    mode: str,
    out: Path,
    fixture: Path | None = None,
    golden: Path | None = None,
    redis_url: str | None = None,
    agg_key_version: str | None = None,
) -> dict[str, Any]:
    fixture = fixture or _DEFAULT_FIXTURE
    golden = golden or _DEFAULT_GOLDEN
    agg = (agg_key_version or os.environ.get("AGG_KEY_VERSION") or "ci_parity_v1").strip()
    ts = datetime.now(UTC).isoformat()

    fixture_meta = _validate_fixture(fixture)
    if not fixture_meta.get("ok"):
        artifact = {
            "schema_id": SCHEMA_ID,
            "ts": ts,
            "mode": mode,
            "matched": False,
            "diffs": [{"kind": "fixture_invalid", "detail": fixture_meta.get("error")}],
            **{k: v for k, v in fixture_meta.items() if k != "ok"},
        }
        write_artifact(out, artifact)
        return artifact

    if mode == "dry_run":
        artifact = {
            "schema_id": SCHEMA_ID,
            "ts": ts,
            "mode": "dry_run",
            "matched": False,
            "diffs": [],
            "events": fixture_meta.get("events"),
            "fixture": fixture_meta.get("fixture"),
            "hint": "dry_run validates fixture only; dual_diff required for matched proof",
        }
        write_artifact(out, artifact)
        return artifact

    if mode != "dual_diff":
        raise ValueError(f"unsupported mode {mode!r}; use dry_run or dual_diff")

    redis_url = (redis_url or os.environ.get("COUNTER_REPLAY_REDIS_URL") or "redis://127.0.0.1:6379").strip()
    base = _base_redis_url(redis_url)
    left_url = f"{base}/14"
    right_url = f"{base}/15"
    scratch_url = f"{base}/13"

    if redis_sync is None:
        artifact = {
            "schema_id": SCHEMA_ID,
            "ts": ts,
            "mode": "dual_diff",
            "matched": False,
            "diffs": [{"kind": "dependency_missing", "detail": "redis package not installed"}],
            "events": fixture_meta.get("events"),
            "fixture": fixture_meta.get("fixture"),
        }
        write_artifact(out, artifact)
        return artifact

    _flush_redis_dbs(left_url, right_url, scratch_url)

    _run_redis_replay(fixture, left_url, agg)
    _run_redis_replay(fixture, right_url, agg)
    _run_redis_replay(fixture, scratch_url, agg)

    diffs = _redis_zset_diffs(left_url, right_url, "fraud:agg*")
    golden_data = _load_golden(golden)
    process = asyncio.run(
        _compute_process_counters(scratch_url, golden_data, agg_key_version=agg)
    )
    diffs.extend(_compare_process_vs_file(process, golden_data))

    artifact = {
        "schema_id": SCHEMA_ID,
        "ts": ts,
        "mode": "dual_diff",
        "matched": len(diffs) == 0,
        "diffs": diffs,
        "events": fixture_meta.get("events"),
        "fixture": fixture_meta.get("fixture"),
        "golden": str(golden.relative_to(_REPO)),
        "agg_key_version": agg,
        "redis_url": redis_url,
        "scratch_redis_url": scratch_url,
    }
    write_artifact(out, artifact)
    return artifact


def write_artifact(out: Path, artifact: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")


def parity_matched(data: dict[str, Any] | None) -> bool:
    """True only when artifact proves dual_diff parity (not dry_run vanity)."""
    if not data or not isinstance(data, dict):
        return False
    if data.get("schema_id") == SCHEMA_ID:
        return data.get("mode") == "dual_diff" and bool(data.get("matched"))
    mode = data.get("mode")
    if mode == "dry_run":
        return False
    if mode in ("redis_dual_diff", "dual_diff"):
        return bool(data.get("ok") or data.get("matched"))
    replay = data.get("replay") or {}
    diff = data.get("diff")
    if replay and diff is not None:
        return bool(replay.get("ok")) and bool((diff or {}).get("ok"))
    return bool(data.get("ok")) and mode not in ("fixture_validate", "dry_run")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("dry_run", "dual_diff"), default="dual_diff")
    p.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    p.add_argument("--golden", type=Path, default=_DEFAULT_GOLDEN)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    p.add_argument(
        "--redis-url",
        default=os.environ.get("COUNTER_REPLAY_REDIS_URL", "redis://127.0.0.1:6379"),
    )
    p.add_argument(
        "--agg-key-version",
        default=os.environ.get("AGG_KEY_VERSION", "ci_parity_v1"),
    )
    args = p.parse_args()

    artifact = run(
        mode=args.mode,
        out=args.out,
        fixture=args.fixture,
        golden=args.golden,
        redis_url=args.redis_url,
        agg_key_version=args.agg_key_version,
    )
    print(json.dumps(artifact, indent=2))
    print(f"wrote {args.out}")
    return 0 if artifact.get("matched") or artifact.get("mode") == "dry_run" else 1


if __name__ == "__main__":
    raise SystemExit(main())
