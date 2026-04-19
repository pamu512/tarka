#!/usr/bin/env python3
"""
Stretch: contract smoke / optional Schemathesis against a running Decision API.

**Minimal smoke (no extra deps):** GET /v1/health and GET /openapi.json

**Full fuzz:** install ``pip install schemathesis`` then use the CLI (recommended)::

  pip install schemathesis
  schemathesis run http://127.0.0.1:8000/openapi.json \\
    --base-url http://127.0.0.1:8000 \\
    --hypothesis-max-examples=20 \\
    --checks=all \\
    --header \"X-API-Key: $SCHEMATHESIS_API_KEY\"

Or point at the repo contract file::

  schemathesis run ../../../contracts/openapi/decision-api.yaml \\
    --base-url http://127.0.0.1:8000 --hypothesis-max-examples=15

This script only verifies reachability and prints the above instructions.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.environ.get("DECISION_API_BASE", "http://127.0.0.1:8000"))
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    for path in ("/v1/health", "/openapi.json"):
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=10) as r:
                assert r.status == 200
        except (urllib.error.URLError, AssertionError, OSError) as e:
            print(f"FAIL {path}: {e}", file=sys.stderr)
            return 1
    print("OK: health + OpenAPI reachable. For property-based fuzz, run:", file=sys.stderr)
    print(
        f"  schemathesis run {base}/openapi.json --base-url {base} --hypothesis-max-examples=20",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
