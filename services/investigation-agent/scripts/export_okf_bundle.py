#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from investigation_agent.okf_exporters import collect_shared_exports, write_staging_bundle


def _repo_root() -> Path:
    override = os.environ.get("OKF_REPO_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export legacy fraud knowledge into an OKF staging bundle (never active roots)."
    )
    parser.add_argument(
        "--rules-dir",
        type=Path,
        required=True,
        help="Directory containing legacy rule JSON (e.g. services/legacy_v1_decision_api/rules)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Staging output directory (e.g. var/okf-staging/shared)",
    )
    parser.add_argument(
        "--include-playbooks",
        action="store_true",
        help="Include built-in investigation playbooks in the export",
    )
    args = parser.parse_args()
    rules_dir = args.rules_dir.resolve()
    if not rules_dir.is_dir():
        print(f"rules-dir is not a directory: {rules_dir}", file=sys.stderr)
        return 1

    repo_root = _repo_root()
    files = collect_shared_exports(rules_dir, include_playbooks=args.include_playbooks)
    try:
        write_staging_bundle(args.output, files, repo_root=repo_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote {len(files)} file(s) to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
