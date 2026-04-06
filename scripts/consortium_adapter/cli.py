#!/usr/bin/env python3
"""CLI for Tarka consortium adapter (share, check, feedback, trust, ingest)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow `python scripts/consortium_adapter/cli.py` from repo root
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from client import ConsortiumAdapter, ingest_json_lines  # noqa: E402


def _build_adapter(url: str, api_key: str) -> ConsortiumAdapter:
    base = url.strip() or os.environ.get("TARKA_DECISION_API_URL", "http://127.0.0.1:8000").strip()
    key = api_key.strip() if api_key.strip() else os.environ.get("TARKA_API_KEY", "").strip()
    return ConsortiumAdapter(base, api_key=key or None)


def main() -> int:
    p = argparse.ArgumentParser(description="Tarka consortium signal adapter")
    p.add_argument(
        "--url",
        default="",
        help="Decision API base URL (default: env TARKA_DECISION_API_URL or http://127.0.0.1:8000)",
    )
    p.add_argument(
        "--api-key",
        default="",
        help="X-API-Key (default: env TARKA_API_KEY if set)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("share", help="POST /v1/consortium/share")
    sp.add_argument("--tenant-id", required=True)
    sp.add_argument("--entity-id", required=True)
    sp.add_argument("--signal-type", required=True)
    sp.add_argument("--severity", type=float, default=1.0)
    sp.add_argument("--ttl-days", type=int, default=30)
    sp.add_argument("--consortium-id", default="")

    cp = sub.add_parser("check", help="GET /v1/consortium/check/...")
    cp.add_argument("--tenant-id", required=True)
    cp.add_argument("--entity-id", required=True)
    cp.add_argument("--consortium-id", default="")

    fp = sub.add_parser("feedback", help="POST /v1/consortium/feedback")
    fp.add_argument("--tenant-id", required=True)
    fp.add_argument("--entity-id", required=True)
    fp.add_argument("--outcome", required=True, choices=("false_positive", "confirmed_fraud"))
    fp.add_argument("--ttl-days", type=int, default=30)
    fp.add_argument("--consortium-id", default="")

    tp = sub.add_parser("trust", help="POST /v1/consortium/trust")
    tp.add_argument("--tenant-id", required=True)
    tp.add_argument("--trust-score", type=float, required=True)
    tp.add_argument("--consortium-id", default="")

    ip = sub.add_parser("ingest", help="Batch JSON Lines file (op share|check|feedback|trust)")
    ip.add_argument("file", type=Path, help="Path to .jsonl")
    ip.add_argument("--dry-run", action="store_true", help="Parse only, no HTTP")

    args = p.parse_args()
    adapter = _build_adapter(args.url, args.api_key)

    try:
        if args.cmd == "share":
            cid = args.consortium_id.strip() or None
            out = adapter.share_signal(
                args.tenant_id,
                args.entity_id,
                args.signal_type,
                severity=args.severity,
                ttl_days=args.ttl_days,
                consortium_id=cid,
            )
        elif args.cmd == "check":
            cid = args.consortium_id.strip() or None
            out = adapter.check_signal(args.tenant_id, args.entity_id, consortium_id=cid)
        elif args.cmd == "feedback":
            cid = args.consortium_id.strip() or None
            out = adapter.post_feedback(
                args.tenant_id,
                args.entity_id,
                args.outcome,
                ttl_days=args.ttl_days,
                consortium_id=cid,
            )
        elif args.cmd == "trust":
            cid = args.consortium_id.strip() or None
            out = adapter.set_tenant_trust(
                args.tenant_id,
                args.trust_score,
                consortium_id=cid,
            )
        elif args.cmd == "ingest":
            text = args.file.read_text(encoding="utf-8")
            ok, err, errors = ingest_json_lines(adapter, text, dry_run=args.dry_run)
            out = {"processed_ok": ok, "errors": err, "messages": errors}
            if errors:
                for m in errors:
                    print(m, file=sys.stderr)
            print(json.dumps(out, indent=2))
            return 1 if err else 0
        else:
            return 2
        print(json.dumps(out, indent=2))
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
