#!/usr/bin/env python3
"""Batch driver for RTBF / erasure — calls decision-api compliance DSAR erasure endpoint.

Usage::

  export DECISION_API_URL=http://localhost:8000
  export TARKA_API_KEY=...
  python3 scripts/compliance/rtbf_batch.py --input entities.csv

CSV columns: tenant_id,entity_id,region (header required).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV with tenant_id,entity_id,region")
    args = ap.parse_args()
    base = (os.environ.get("DECISION_API_URL") or "http://localhost:8000").rstrip("/")
    key = (os.environ.get("TARKA_API_KEY") or "").strip() or os.environ.get("API_KEYS", "").split(",")[0].strip()
    if not key:
        print("Set TARKA_API_KEY or API_KEYS", file=sys.stderr)
        raise SystemExit(2)

    ok = 0
    with open(args.input, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = (row.get("tenant_id") or "").strip()
            eid = (row.get("entity_id") or "").strip()
            region = (row.get("region") or "global").strip()
            if not tid or not eid:
                continue
            body = json.dumps({"tenant_id": tid, "entity_id": eid, "region": region}).encode()
            req = urllib.request.Request(
                f"{base}/v1/compliance/dsar/erasure",
                data=body,
                headers={"Content-Type": "application/json", "X-API-Key": key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    if resp.status == 200:
                        ok += 1
            except urllib.error.HTTPError as e:
                print(f"FAIL {tid}/{eid}: {e.code}", file=sys.stderr)
    print(f"completed_requests={ok}")


if __name__ == "__main__":
    main()
