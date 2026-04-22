#!/usr/bin/env python3
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

"""Batch score rows via ml-scoring ``POST /v1/score`` (v1.2 stretch — analyst dry-runs).

Reads a CSV with at least ``tenant_id`` and ``entity_id``. Feature columns are every column
except reserved names (see ``--help``). Optional ``event_type`` column. Optional ``features``
column: if present, JSON object merged on top of per-column features.

Requires ``httpx`` (``pip install -r scripts/requirements.txt`` from repo root).

Example::

    python scripts/ml_batch_score.py \\
      --url http://127.0.0.1:8005 \\
      --input rows.csv \\
      --output scores.csv

See also ``scripts/benchmarks/README.md``.
"""
RESERVED = frozenset(
    {
        "tenant_id",
        "entity_id",
        "event_type",
        "features",
        "ml_score",
        "ml_model",
        "ml_summary",
        "error",
    }
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:8005", help="ml-scoring base URL")
    p.add_argument("--input", "-i", required=True, type=Path, help="Input CSV path")
    p.add_argument("--output", "-o", type=Path, help="Output CSV (default: stdout)")
    p.add_argument(
        "--api-key",
        default="",
        help="Optional X-API-Key header when ml-scoring enforces API_KEYS",
    )
    p.add_argument("--timeout", type=float, default=30.0)
    return p.parse_args()


def _row_features(row: dict[str, str]) -> dict[str, Any]:
    feats: dict[str, Any] = {}
    raw = (row.get("features") or "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, dict):
                feats.update(extra)
        except json.JSONDecodeError:
            pass
    for k, v in row.items():
        if k in RESERVED:
            continue
        if v is None or v == "":
            continue
        try:
            if "." in v or "e" in v.lower():
                feats[k] = float(v)
            else:
                feats[k] = int(v)
        except ValueError:
            feats[k] = v
    return feats


def main() -> int:
    try:
        import httpx
    except ImportError:
        print("Install httpx: pip install -r scripts/requirements.txt", file=sys.stderr)
        return 1

    args = _parse_args()
    if not args.input.is_file():
        print(f"Not a file: {args.input}", file=sys.stderr)
        return 1

    headers: dict[str, str] = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    rows_out: list[dict[str, Any]] = []
    input_fieldnames: list[str] = []

    with args.input.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            print("CSV has no header row", file=sys.stderr)
            return 1
        input_fieldnames = list(reader.fieldnames)
        for row in reader:
            tid = (row.get("tenant_id") or "").strip()
            eid = (row.get("entity_id") or "").strip()
            if not tid or not eid:
                rows_out.append({**row, "error": "missing tenant_id or entity_id"})
                continue
            body: dict[str, Any] = {
                "tenant_id": tid,
                "entity_id": eid,
                "features": _row_features(row),
            }
            et = (row.get("event_type") or "").strip()
            if et:
                body["event_type"] = et
            try:
                with httpx.Client(timeout=args.timeout) as client:
                    r = client.post(
                        f"{args.url.rstrip('/')}/v1/score",
                        json=body,
                        headers=headers,
                    )
                if r.status_code >= 400:
                    rows_out.append({**row, "error": f"HTTP {r.status_code}: {r.text[:200]}"})
                    continue
                data = r.json()
                out_row = {
                    **row,
                    "ml_score": data.get("score"),
                    "ml_model": data.get("model"),
                    "ml_summary": data.get("ml_summary") or "",
                    "error": "",
                }
                rows_out.append(out_row)
            except Exception as exc:
                rows_out.append({**row, "error": str(exc)[:500]})

    out_fields = list(input_fieldnames)
    for k in ("ml_score", "ml_model", "ml_summary", "error"):
        if k not in out_fields:
            out_fields.append(k)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=out_fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_out)
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
