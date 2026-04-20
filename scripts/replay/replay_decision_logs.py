#!/usr/bin/env python3
"""Replay canonical decision logs against a target Decision API and diff decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _build_replay_request(row: dict[str, Any]) -> dict[str, Any]:
    snap = row.get("payload_snapshot") or {}
    payload = snap.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    metadata = snap.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    out = {
        "tenant_id": row.get("tenant_id"),
        "event_type": row.get("event_type"),
        "entity_id": row.get("entity_id"),
        "payload": payload,
        "metadata": metadata,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay decision log JSONL into Decision API")
    parser.add_argument("--input", required=True, help="Path to decision-log.jsonl")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    path = Path(args.input)
    if not path.is_file():
        raise SystemExit(f"missing input file: {path}")

    changed = 0
    processed = 0
    with httpx.Client(timeout=8.0) as client:
        for row in _iter_jsonl(path):
            req = _build_replay_request(row)
            headers = {"content-type": "application/json"}
            if args.api_key:
                headers["x-api-key"] = args.api_key
            response = client.post(f"{args.base_url.rstrip('/')}/v1/decisions/evaluate", headers=headers, json=req)
            if response.status_code != 200:
                continue
            fresh = response.json()
            if str(fresh.get("decision")) != str(row.get("decision")):
                changed += 1
            processed += 1
            if processed >= max(1, args.limit):
                break

    print(
        json.dumps(
            {
                "processed": processed,
                "decision_changed": changed,
                "decision_change_rate": round((changed / processed), 4) if processed else 0.0,
                "input": str(path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
