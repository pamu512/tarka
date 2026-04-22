#!/usr/bin/env python3
from __future__ import annotations

"""
Replay JSONL audit/export rows into a scratch Redis so aggregate keys can be diffed against prod.

See docs/docs/guides/counter-replay-parity.md and docs/docs/guides/ingest-replay-onboarding.md.

Expected JSONL shapes (one object per line):
  - Minimal: {"tenant_id": "...", "entity_id": "...", "event_id": "...", "fields": {"amount": 1.0}}
  - With ts: optional top-level "ts" (unix) for ZSET scores; if missing, metadata.event_time / fields.event_time parsed like evaluate
  - Audit-like: {"tenant_id": "...", "entity_id": "...", "trace_id": "...", "payload": {...}}
    (payload dict is passed as aggregate fields when "fields" is absent)
"""


import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED = _REPO_ROOT / "services" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from event_time import event_time_unix_for_evaluate  # noqa: E402


def _ensure_import_paths() -> None:
    shared = _REPO_ROOT / "services" / "shared"
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))


def iter_audit_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def parse_time_bound(raw: str) -> float:
    """Parse unix-seconds or ISO-8601 into epoch seconds."""
    s = str(raw).strip()
    if not s:
        raise ValueError("empty time bound")
    try:
        return float(s)
    except ValueError:
        pass
    # Accept `Z` suffix in addition to offset-aware ISO.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    ts = dt.datetime.fromisoformat(s)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.timestamp()


def row_timestamp_seconds(row: dict[str, Any]) -> float | None:
    """Best-effort event timestamp from canonical fields."""
    for key in ("ts", "created_at", "event_ts", "timestamp"):
        v = row.get(key)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            try:
                return float(s)
            except ValueError:
                try:
                    return parse_time_bound(s)
                except ValueError:
                    continue
    return None


def row_to_record_args(row: dict[str, Any]) -> tuple[str, str, str, dict[str, Any], float | None] | None:
    tenant_id = row.get("tenant_id")
    entity_id = row.get("entity_id")
    if not tenant_id or not entity_id:
        return None
    event_id = row.get("event_id") or row.get("trace_id") or row.get("ingest_id") or row.get("_ingest_id") or uuid.uuid4().hex
    fields = row.get("fields")
    if fields is None:
        payload = row.get("payload") or row.get("request_body") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        fields = dict(payload) if isinstance(payload, dict) else {}
    elif not isinstance(fields, dict):
        fields = {}
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
    ts = row.get("ts")
    ts_f: float | None = float(ts) if ts is not None else None
    if ts_f is None:
        ts_f = event_time_unix_for_evaluate(meta, fields)
    return str(tenant_id), str(entity_id), str(event_id), fields, ts_f


async def replay_to_redis(
    path: Path,
    redis_url: str,
    *,
    limit: int | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    dry_run: bool,
) -> int:
    _ensure_import_paths()
    import redis.asyncio as aioredis
    from fraud_aggregates import AGG_PREFIX, AggregateStore

    count = 0
    skipped = 0
    client = None if dry_run else aioredis.from_url(redis_url, decode_responses=True)
    try:
        store = AggregateStore(client)
        for row in iter_audit_rows(path):
            if limit is not None and count >= limit:
                break
            row_ts = row_timestamp_seconds(row)
            if from_ts is not None and (row_ts is None or row_ts < from_ts):
                continue
            if to_ts is not None and (row_ts is None or row_ts > to_ts):
                continue
            parsed = row_to_record_args(row)
            if parsed is None:
                skipped += 1
                continue
            tenant_id, entity_id, event_id, fields, ts = parsed
            if dry_run:
                count += 1
                continue
            assert client is not None
            await store.record_event(tenant_id, entity_id, event_id, fields, ts=ts)
            count += 1
    finally:
        if client is not None:
            await client.aclose()

    prefix_note = f"Keys use prefix {AGG_PREFIX!r} on the target Redis."
    if dry_run:
        print(f"Dry-run: parsed {count} row(s), skipped {skipped} (missing tenant/entity). {prefix_note}")
    else:
        print(f"Replayed {count} event(s) into Redis, skipped {skipped}. {prefix_note}")
    if count == 0 and skipped > 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay JSONL rows into Redis-backed AggregateStore (offline parity / v1.2).")
    p.add_argument("--input", type=Path, help="JSONL file (one JSON object per line)")
    p.add_argument(
        "--redis-url",
        type=str,
        default="",
        help="Redis URL for scratch DB (e.g. redis://localhost:6379/15). Required unless --dry-run.",
    )
    p.add_argument("--limit", type=int, default=None, help="Max rows to process")
    p.add_argument(
        "--from-ts",
        type=str,
        default="",
        help="Inclusive lower timestamp bound (unix seconds or ISO-8601, e.g. 2026-04-01T00:00:00Z)",
    )
    p.add_argument(
        "--to-ts",
        type=str,
        default="",
        help="Inclusive upper timestamp bound (unix seconds or ISO-8601)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count rows only; no Redis writes",
    )
    p.add_argument(
        "--manifest-info",
        action="store_true",
        help="Print bundled counter-manifest version/path and exit (no Redis)",
    )
    args = p.parse_args(argv)

    if args.manifest_info:
        mp = _REPO_ROOT / "services" / "decision-api" / "src" / "decision_api" / "data" / "counter_manifest_v1.json"
        if not mp.is_file():
            print(f"Manifest not found: {mp}", file=sys.stderr)
            return 1
        data = json.loads(mp.read_text(encoding="utf-8"))
        print(f"counter_manifest_v1.json: {mp}")
        print(f"manifest_version: {data.get('manifest_version', '?')}")
        print(f"feature_outputs: {len(data.get('feature_outputs', []))}")
        return 0

    if not args.input:
        p.print_help()
        return 0

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    if not args.dry_run and not args.redis_url.strip():
        print("Provide --redis-url or use --dry-run.", file=sys.stderr)
        return 1

    from_ts: float | None = None
    to_ts: float | None = None
    if str(args.from_ts).strip():
        try:
            from_ts = parse_time_bound(args.from_ts)
        except ValueError as exc:
            print(f"Invalid --from-ts: {exc}", file=sys.stderr)
            return 1
    if str(args.to_ts).strip():
        try:
            to_ts = parse_time_bound(args.to_ts)
        except ValueError as exc:
            print(f"Invalid --to-ts: {exc}", file=sys.stderr)
            return 1
    if from_ts is not None and to_ts is not None and from_ts > to_ts:
        print("--from-ts must be <= --to-ts", file=sys.stderr)
        return 1

    return asyncio.run(
        replay_to_redis(
            args.input,
            args.redis_url.strip(),
            limit=args.limit,
            from_ts=from_ts,
            to_ts=to_ts,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
