#!/usr/bin/env python3
from __future__ import annotations
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

"""
Probe a running investigation-agent for GET /v1/integration (adapter parity / smoke).

Example:
  python scripts/ci/check_integration_contract.py --base-url http://localhost:8006

Optional headers for deployments that require x-api-key:
  python scripts/ci/check_integration_contract.py --base-url https://agent.example --api-key secret
"""

def main() -> int:
    p = argparse.ArgumentParser(description="GET /v1/integration and validate shape")
    p.add_argument("--base-url", default="http://localhost:8006", help="Agent base URL (no trailing slash)")
    p.add_argument("--api-key", default="", help="Optional x-api-key header")
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    url = f"{base}/v1/integration"
    req = urllib.request.Request(url, method="GET")
    if args.api_key.strip():
        req.add_header("x-api-key", args.api_key.strip())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("Response is not JSON", file=sys.stderr)
        return 1
    required = (
        "contract_version",
        "profile_id",
        "upstream_configured",
        "tools",
        "families_enabled",
        "maker_checker",
    )
    missing = [k for k in required if k not in data]
    if missing:
        print(f"Missing keys: {missing}", file=sys.stderr)
        return 1
    tools = data.get("tools") or {}
    if "disabled_effective" not in tools:
        print("tools.disabled_effective missing (contract 1.1+)", file=sys.stderr)
        return 1
    if not isinstance(tools.get("enabled"), list) or len(tools["enabled"]) < 1:
        print("tools.enabled must be a non-empty list", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "contract_version": data["contract_version"], "profile_id": data["profile_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
