#!/usr/bin/env python3
"""Wave 5: prod desk must forbid VITE_USE_API_MOCKS=true (static gate)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLIENT = _REPO / "frontend" / "src" / "api" / "client.ts"


def main() -> int:
    if not _CLIENT.is_file():
        print(f"missing {_CLIENT}", file=sys.stderr)
        return 1
    text = _CLIENT.read_text(encoding="utf-8")
    errors: list[str] = []

    if "IS_PRODUCTION_BUILD" not in text:
        errors.append("client.ts missing IS_PRODUCTION_BUILD")
    if not re.search(
        r"IS_PRODUCTION_BUILD\s*&&\s*MOCK_MODE\s*===\s*[\"']true[\"']",
        text,
    ):
        errors.append(
            "client.ts must forbid VITE_USE_API_MOCKS=true in production builds"
        )
    if "forbidden in production builds" not in text:
        errors.append("client.ts missing production mock forbid Error message")

    policy = _REPO / "frontend" / "src" / "api" / "deskMockPolicy.ts"
    if not policy.is_file():
        errors.append("missing deskMockPolicy.ts (VITE_DESK_STRICT)")
    else:
        pol = policy.read_text(encoding="utf-8")
        if "deskStrictEnabled" not in pol or "isDeskApiPath" not in pol:
            errors.append("deskMockPolicy.ts missing desk-strict helpers")
    if "allowMocksForRequest" not in text and "mocksAllowedForUrl" not in text:
        errors.append("client.ts must use desk-strict mock allowlist")

    desk_files = [
        _REPO / "frontend" / "src" / "api" / "v1" / "decisions.ts",
        _REPO / "frontend" / "src" / "api" / "v1" / "disputes.ts",
    ]
    for path in desk_files:
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"from\s+[\"'].*mockData", src):
            errors.append(f"{path.relative_to(_REPO)} statically imports mockData")

    if errors:
        print("audit_prod_desk_mocks: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("audit_prod_desk_mocks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
