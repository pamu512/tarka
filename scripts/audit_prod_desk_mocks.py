#!/usr/bin/env python3
"""Prod/lean desk mock forbid gate (Wave 5 + Engineering 4.7)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CLIENT = _REPO / "frontend" / "src" / "api" / "client.ts"

LEAN_DESK_PAGE_FILES = [
    "frontend/src/pages/Cases.tsx",
    "frontend/src/pages/CaseDetail.tsx",
    "frontend/src/pages/OpsQaDesk.tsx",
    "frontend/src/pages/OpsCalibration.tsx",
    "frontend/src/pages/Disputes.tsx",
    "frontend/src/pages/OpsCounters.tsx",
    "frontend/src/pages/OpsSarTransportBoard.tsx",
    "frontend/src/pages/RulePerformance.tsx",
]

_FORBIDDEN_LEAN_PATHS = (
    "/simulation",
    "/shadow",
    "/investigation",
    "/admin",
    "/command-center",
)

_MOCK_IMPORT_RE = re.compile(
    r"""from\s+["'][^"']*mockData[^"']*["']|import\s*\(\s*["'][^"']*mockData"""
)


def scan_lean_desk_violations(repo: Path) -> list[str]:
    """Return lean-desk honesty violations (mockData imports / broad LEAN_NAV)."""
    errors: list[str] = []
    for rel in LEAN_DESK_PAGE_FILES:
        path = repo / rel
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        if _MOCK_IMPORT_RE.search(src):
            errors.append(f"{rel} imports mockData (forbidden on lean desk)")
    v1_dir = repo / "frontend" / "src" / "api" / "v1"
    if v1_dir.is_dir():
        for path in sorted(v1_dir.glob("*.ts")):
            src = path.read_text(encoding="utf-8")
            if _MOCK_IMPORT_RE.search(src):
                errors.append(f"{path.relative_to(repo)} imports mockData")
    lean = repo / "frontend" / "src" / "config" / "leanNav.ts"
    if lean.is_file():
        text = lean.read_text(encoding="utf-8")
        if "LEAN_NAV_PATHS" in text:
            block = text.split("LEAN_NAV_PATHS", 1)[-1].split(";", 1)[0]
            for bad in _FORBIDDEN_LEAN_PATHS:
                if f'"{bad}"' in block or f"'{bad}'" in block:
                    errors.append(f"leanNav.ts LEAN_NAV_PATHS must not include {bad}")
    return errors


def main(repo: Path | None = None) -> int:
    root = repo or _REPO
    client = root / "frontend" / "src" / "api" / "client.ts"
    if not client.is_file():
        print(f"missing {client}", file=sys.stderr)
        return 1
    text = client.read_text(encoding="utf-8")
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

    policy = root / "frontend" / "src" / "api" / "deskMockPolicy.ts"
    if not policy.is_file():
        errors.append("missing deskMockPolicy.ts (VITE_DESK_STRICT)")
    else:
        pol = policy.read_text(encoding="utf-8")
        if "deskStrictEnabled" not in pol or "isDeskApiPath" not in pol:
            errors.append("deskMockPolicy.ts missing desk-strict helpers")
    if "allowMocksForRequest" not in text and "mocksAllowedForUrl" not in text:
        errors.append("client.ts must use desk-strict mock allowlist")

    desk_files = [
        root / "frontend" / "src" / "api" / "v1" / "decisions.ts",
        root / "frontend" / "src" / "api" / "v1" / "disputes.ts",
        root / "frontend" / "src" / "api" / "v1" / "cases.ts",
    ]
    for path in desk_files:
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"from\s+[\"'].*mockData", src):
            errors.append(f"{path.relative_to(root)} statically imports mockData")

    errors.extend(scan_lean_desk_violations(root))

    if errors:
        print("audit_prod_desk_mocks: FAIL", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("audit_prod_desk_mocks: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
