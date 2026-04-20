#!/usr/bin/env python3
"""
N4.2 — weekly aggregate export stub (machine-readable JSON artifact).

Fetches analytics-sink ``GET /v1/analytics/scorecard`` and writes pretty-printed JSON
to ``--output`` or stdout. Intended for cron (weekly) or object storage upload; pairs
with OSS #53 (Discussions publish uses the same upstream JSON).

Environment (optional defaults):
  SCORECARD_BASE_URL   Gateway base, e.g. https://example.com/api/analytics
  SCORECARD_API_KEY    x-api-key header when analytics-sink requires auth
  SCORECARD_TENANT_ID  default: demo
  SCORECARD_DAYS       default: 7

Example:
  SCORECARD_BASE_URL=https://localhost/api/analytics python3 scripts/analytics/export_weekly_scorecard_json.py -o exports/scorecard-demo.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def fetch_scorecard(base_url: str, tenant_id: str, days: int, api_key: str) -> dict:
    q = urllib.parse.urlencode({"tenant_id": tenant_id, "days": str(days)})
    url = f"{base_url.rstrip('/')}/v1/analytics/scorecard?{q}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if api_key:
        req.add_header("x-api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from scorecard: {detail[:800]}") from None


def main() -> int:
    p = argparse.ArgumentParser(description="Export weekly decision scorecard JSON (analytics-sink).")
    p.add_argument("--base-url", default=os.environ.get("SCORECARD_BASE_URL", "").strip())
    p.add_argument("--tenant-id", default=os.environ.get("SCORECARD_TENANT_ID", "demo"))
    p.add_argument("--days", type=int, default=int(os.environ.get("SCORECARD_DAYS", "7")))
    p.add_argument("--api-key", default=os.environ.get("SCORECARD_API_KEY", ""))
    p.add_argument(
        "-o",
        "--output",
        help="Write JSON to this path (default: stdout)",
    )
    args = p.parse_args()

    if not args.base_url:
        print("ERROR: set --base-url or SCORECARD_BASE_URL", file=sys.stderr)
        return 1

    envelope = {
        "schema": "tarka_weekly_scorecard_export_v1",
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "GET /v1/analytics/scorecard",
        "service": "analytics-sink",
        "data": fetch_scorecard(args.base_url, args.tenant_id, args.days, args.api_key),
    }
    text = json.dumps(envelope, indent=2) + "\n"
    if args.output:
        out_path = os.path.abspath(args.output)
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(out_path, file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
