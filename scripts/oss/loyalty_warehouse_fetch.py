#!/usr/bin/env python3
"""Fetch loyalty warehouse pack from HTTP URL → evaluate-ready JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "decision-api" / "src"))

from decision_api.loyalty_warehouse import (  # noqa: E402
    LoyaltyWarehouseError,
    fetch_loyalty_warehouse_pack,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="Warehouse pack HTTP URL")
    p.add_argument("--out", type=Path, help="Write pack JSON (default stdout)")
    p.add_argument("--timeout", type=float, default=10.0)
    args = p.parse_args()
    try:
        pack = fetch_loyalty_warehouse_pack(args.url, timeout=args.timeout)
    except LoyaltyWarehouseError as exc:
        print(f"loyalty_warehouse_fetch: FAIL {exc}", file=sys.stderr)
        return 1
    text = json.dumps(pack, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
