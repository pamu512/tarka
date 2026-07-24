#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from investigation_agent.okf_exporters import (
    collect_shared_exports,
    export_landmark_case_bundle,
    write_staging_bundle,
)


def _repo_root() -> Path:
    override = os.environ.get("OKF_REPO_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export legacy fraud knowledge or one sanitized landmark case into an "
            "OKF staging bundle (never active roots)."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--rules-dir",
        type=Path,
        help="Directory containing legacy rule JSON (e.g. services/legacy_v1_decision_api/rules)",
    )
    source.add_argument(
        "--landmark-input",
        type=Path,
        help="Sanitized landmark case JSON; source hash is generated, not accepted",
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
    parser.add_argument(
        "--tenant-id",
        default="",
        help="Required with --landmark-input; tenant scope for the overlay concept",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    try:
        if args.rules_dir is not None:
            rules_dir = args.rules_dir.resolve()
            if not rules_dir.is_dir():
                raise ValueError(f"rules-dir is not a directory: {rules_dir}")
            files = collect_shared_exports(
                rules_dir,
                include_playbooks=args.include_playbooks,
            )
        else:
            if args.include_playbooks:
                raise ValueError("--include-playbooks is only valid with --rules-dir")
            tenant_id = str(args.tenant_id).strip()
            if not tenant_id:
                raise ValueError("--tenant-id is required with --landmark-input")
            raw = args.landmark_input.read_text(encoding="utf-8")
            case = json.loads(raw)
            if not isinstance(case, dict):
                raise ValueError("landmark input must be a JSON object")
            if "source_content_hash" in case:
                raise ValueError(
                    "source_content_hash must not be supplied; canonical snapshot provenance is generated"
                )
            files = export_landmark_case_bundle(case, tenant_id=tenant_id)
        write_staging_bundle(args.output, files, repo_root=repo_root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote {len(files)} file(s) to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
