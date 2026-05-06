#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

"""
N4.2 — weekly aggregate export with integrity metadata.

Fetches analytics-sink ``GET /v1/analytics/scorecard`` and writes machine-readable JSON
to ``--output`` or stdout, including artifact hash + byte count. Supports optional
object-store style upload via pre-signed HTTP PUT URL.

Environment (optional defaults):
  SCORECARD_BASE_URL   Gateway base, e.g. https://example.com/api/analytics
  SCORECARD_API_KEY    x-api-key header when analytics-sink requires auth
  SCORECARD_TENANT_ID  default: demo
  SCORECARD_DAYS       default: 7
  SCORECARD_UPLOAD_URL optional PUT target for durable artifact storage
  SCORECARD_UPLOAD_API_KEY optional x-api-key for upload target

Example:
  SCORECARD_BASE_URL=https://localhost/api/analytics python3 scripts/analytics/export_weekly_scorecard_json.py -o exports/scorecard-demo.json
"""


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


def upload_artifact(upload_url: str, payload: bytes, api_key: str) -> dict:
    req = urllib.request.Request(upload_url, data=payload, method="PUT")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("x-api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return {"status": resp.status, "ok": 200 <= resp.status < 300}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} from upload target: {detail[:800]}") from None


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export weekly decision scorecard JSON (analytics-sink)."
    )
    p.add_argument("--base-url", default=os.environ.get("SCORECARD_BASE_URL", "").strip())
    p.add_argument("--tenant-id", default=os.environ.get("SCORECARD_TENANT_ID", "demo"))
    p.add_argument("--days", type=int, default=int(os.environ.get("SCORECARD_DAYS", "7")))
    p.add_argument("--api-key", default=os.environ.get("SCORECARD_API_KEY", ""))
    p.add_argument(
        "--upload-url",
        default=os.environ.get("SCORECARD_UPLOAD_URL", "").strip(),
        help="Optional pre-signed/object-store upload URL (HTTP PUT)",
    )
    p.add_argument(
        "--upload-api-key",
        default=os.environ.get("SCORECARD_UPLOAD_API_KEY", ""),
        help="Optional x-api-key header for upload target",
    )
    p.add_argument(
        "-o",
        "--output",
        help="Write JSON to this path (default: stdout)",
    )
    args = p.parse_args()

    if not args.base_url:
        print("ERROR: set --base-url or SCORECARD_BASE_URL", file=sys.stderr)
        return 1

    fetched = fetch_scorecard(args.base_url, args.tenant_id, args.days, args.api_key)
    exported_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    artifact_name = (
        f"scorecard-{args.tenant_id}-{exported_at.replace(':', '').replace('-', '')}.json"
    )
    envelope = {
        "schema": "tarka_weekly_scorecard_export_v1",
        "exported_at": exported_at,
        "source": "GET /v1/analytics/scorecard",
        "service": "analytics-sink",
        "artifact": {
            "name": artifact_name,
            "tenant_id": args.tenant_id,
            "window_days": int(args.days),
            "source_url": f"{args.base_url.rstrip('/')}/v1/analytics/scorecard",
        },
        "data": fetched,
    }
    text = json.dumps(envelope, indent=2) + "\n"
    payload_bytes = text.encode("utf-8")
    envelope["artifact"]["sha256"] = hashlib.sha256(payload_bytes).hexdigest()
    envelope["artifact"]["byte_count"] = len(payload_bytes)
    text = json.dumps(envelope, indent=2) + "\n"
    payload_bytes = text.encode("utf-8")
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

    if args.upload_url:
        result = upload_artifact(args.upload_url, payload_bytes, args.upload_api_key)
        status = result.get("status")
        if result.get("ok") is True:
            print(f"uploaded scorecard artifact via PUT ({status})", file=sys.stderr)
        else:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
