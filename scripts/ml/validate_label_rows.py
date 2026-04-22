#!/usr/bin/env python3
from __future__ import annotations

"""
Validate label rows (JSONL or single JSON object).

Required: trace_id, tenant_id, label.

Optional checks (default on, use --minimal to skip):
  - trace_id matches safe pattern for filesystem keys
  - decision_ts is ISO-8601 when present
  - features_snapshot_ref uses https / s3 / gs / file scheme when present
  - label in allowed set when --allowed-labels is passed

Usage:
  python scripts/ml/validate_label_rows.py path/to/labels.jsonl
  python scripts/ml/validate_label_rows.py --allowed-labels fraud,legit,suspect data.jsonl
"""


import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REQUIRED = ("trace_id", "tenant_id", "label")
_TRACE_RE = re.compile(r"^[a-zA-Z0-9._:@-]{8,128}$")
_REF_SCHEMES = ("https://", "s3://", "gs://", "file://")


def _required_ok(obj: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in _REQUIRED:
        if k not in obj or obj[k] in (None, ""):
            errs.append(f"missing_or_empty:{k}")
    return errs


def _extended_ok(obj: dict[str, Any], allowed_labels: frozenset[str] | None) -> list[str]:
    errs: list[str] = []
    tid = str(obj.get("trace_id", ""))
    if tid and not _TRACE_RE.match(tid):
        errs.append("trace_id_unsafe_or_invalid")

    ts = obj.get("decision_ts")
    if ts is not None and str(ts).strip() != "":
        s = str(ts).strip().replace("Z", "+00:00")
        try:
            datetime.fromisoformat(s)
        except ValueError:
            errs.append("decision_ts_not_iso8601")

    ref = obj.get("features_snapshot_ref")
    if ref is not None and str(ref).strip() != "":
        u = str(ref).strip()
        if not u.startswith(_REF_SCHEMES):
            errs.append("features_snapshot_ref_must_be_https_s3_gs_or_file")

    if allowed_labels is not None:
        lab = str(obj.get("label", "")).strip().lower()
        if lab not in allowed_labels:
            errs.append(f"label_not_allowed:{lab!r}")

    return errs


def _row_errors(
    obj: dict[str, Any],
    *,
    minimal: bool,
    allowed_labels: frozenset[str] | None,
) -> list[str]:
    errs = _required_ok(obj)
    if errs:
        return errs
    if minimal:
        if allowed_labels is not None:
            lab = str(obj.get("label", "")).strip().lower()
            if lab not in allowed_labels:
                errs.append(f"label_not_allowed:{lab!r}")
        return errs
    errs.extend(_extended_ok(obj, allowed_labels))
    return errs


def _load_objects(path: Path) -> list[tuple[int, dict[str, Any]]]:
    text = path.read_text(encoding="utf-8").strip()
    objects: list[tuple[int, dict[str, Any]]] = []
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                objects.append((1, obj))
                return objects
        except json.JSONDecodeError:
            pass
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise ValueError(f"line {i}: expected object")
        objects.append((i, obj))
    return objects


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--minimal", action="store_true", help="Only require trace_id, tenant_id, label")
    p.add_argument(
        "--allowed-labels",
        default="",
        help="Comma-separated allowed label values (e.g. fraud,legit,suspect). Empty = no enum check.",
    )
    args = p.parse_args()
    path = args.path
    if not path.is_file():
        print(f"Not found: {path}", file=sys.stderr)
        return 1

    allowed: frozenset[str] | None = None
    if args.allowed_labels.strip():
        allowed = frozenset(x.strip().lower() for x in args.allowed_labels.split(",") if x.strip())

    try:
        objects = _load_objects(path)
    except (json.JSONDecodeError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    bad = 0
    for i, obj in objects:
        errs = _row_errors(obj, minimal=args.minimal, allowed_labels=allowed)
        if errs:
            print(f"line {i}: {errs}", file=sys.stderr)
            bad += 1
    if bad:
        print(f"FAIL: {bad} invalid rows", file=sys.stderr)
        return 1
    print("OK: all rows valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
