#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

"""
Upload Markdown files to investigation-agent knowledge (POST /v1/knowledge/ingest).

Example:
  export INGEST_BASE_URL=http://localhost:8006
  python scripts/ingest_wiki_markdown.py --dir ./wiki_export --tenant-id demo --analyst-id a1

Requires: httpx (same as investigation-agent).
"""

def main() -> int:
    p = argparse.ArgumentParser(description="Ingest .md files into Saarthi knowledge RAG")
    p.add_argument("--base-url", default="http://localhost:8006", help="Agent base URL")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--analyst-id", required=True)
    p.add_argument("--dir", type=Path, required=True, help="Directory of .md files")
    p.add_argument("--api-key", default="", help="Optional x-api-key header")
    args = p.parse_args()
    root: Path = args.dir
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    headers = {"Content-Type": "application/json"}
    if args.api_key.strip():
        headers["x-api-key"] = args.api_key.strip()

    url = f"{args.base_url.rstrip('/')}/v1/knowledge/ingest"
    count = 0
    with httpx.Client(timeout=120.0) as client:
        for path in sorted(root.rglob("*.md")):
            body_text = path.read_text(encoding="utf-8", errors="replace")
            title = path.stem.replace("_", " ")[:256]
            payload = {
                "tenant_id": args.tenant_id,
                "analyst_id": args.analyst_id,
                "title": f"{title} ({path.relative_to(root)})",
                "body": body_text,
            }
            r = client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                print(f"FAIL {path}: {r.status_code} {r.text[:500]}", file=sys.stderr)
                return 1
            count += 1
            print(f"OK {path} -> {r.json().get('doc_id', '?')}")

    print(f"Ingested {count} markdown file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
