#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from investigation_agent.okf_parser import validate_bundle


def _print_issues(result) -> None:
    payload = [
        {"code": issue.code, "path": issue.path, "message": issue.message}
        for issue in result.issues
    ]
    print(json.dumps(payload, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an OKF bundle directory.")
    parser.add_argument("root", type=Path, help="Bundle root directory")
    parser.add_argument(
        "--scope",
        choices=("shared", "tenant"),
        required=True,
        help="Bundle scope (shared or tenant overlay)",
    )
    parser.add_argument(
        "--tenant-id",
        default="",
        help="Tenant id (required when scope=tenant)",
    )
    parser.add_argument(
        "--shared-root",
        type=Path,
        default=None,
        help=("Approved shared bundle root used to resolve tenant /shared/... logical links"),
    )
    args = parser.parse_args()
    tenant_id: str | None = args.tenant_id.strip() or None
    if args.scope == "tenant" and not tenant_id:
        print("tenant-id is required for tenant scope", file=sys.stderr)
        return 1

    shared_bundle = None
    if args.scope == "tenant" and args.shared_root is not None:
        shared_result = validate_bundle(
            args.shared_root.resolve(),
            scope="shared",
            tenant_id=None,
        )
        if not shared_result.valid:
            _print_issues(shared_result)
            return 1
        shared_bundle = shared_result.bundle

    result = validate_bundle(
        args.root.resolve(),
        scope=args.scope,
        tenant_id=tenant_id,
        shared_bundle=shared_bundle,
    )
    if result.valid:
        return 0

    _print_issues(result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
