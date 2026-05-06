#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

"""
Build a supervised training table from label rows + feature snapshots (ROI pipeline).

Expected input:
  - Label JSONL/CSV with fields compatible with contracts/training/label_row_v1.example.json
  - Per-trace feature dicts (JSON or Parquet) keyed by trace_id, captured at *decision time*

Output:
  - training_matrix.parquet (or CSV) with columns matching ml_scoring.heuristic.FEATURE_ORDER
  - manifest.json with row counts, catalog_ref, and time window

This script does not call live services; it stitches files you export from audit/feature store.
"""
_SCRIPTS_ML = Path(__file__).resolve().parent
if str(_SCRIPTS_ML) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ML))
from feature_order import get_feature_order  # noqa: E402

# Safe trace_id for filesystem keys (reject path traversal and odd chars)
_TRACE_ID_RE = re.compile(r"^[a-zA-Z0-9._:@-]{8,128}$")


def _feature_order() -> list[str]:
    return get_feature_order()


def _row_from_features(feat: dict[str, Any], order: list[str]) -> list[float | int]:
    out: list[float | int] = []
    for k in order:
        v = feat.get(k)
        if v is None and k == "is_new_device":
            v = feat.get("new_device")
        if isinstance(v, bool):
            out.append(1.0 if v else 0.0)
        elif v is None:
            out.append(0.0)
        else:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                out.append(0.0)
    return out


def _validate_label_line(obj: dict[str, Any]) -> str | None:
    for k in ("trace_id", "tenant_id", "label"):
        if k not in obj or obj[k] in (None, ""):
            return k
    tid = str(obj.get("trace_id", ""))
    if not _TRACE_ID_RE.match(tid):
        return "trace_id(unsafe_or_invalid)"
    return None


def _iter_label_objects(text: str) -> list[dict[str, Any]]:
    """Parse JSONL or a single JSON object (pretty-printed)."""
    text = text.strip()
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return [obj]
        except json.JSONDecodeError:
            pass
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def main() -> int:
    p = argparse.ArgumentParser(
        description="Build ML training matrix from labels + feature snapshots"
    )
    p.add_argument(
        "--labels", type=Path, required=True, help="JSONL file; one label object per line"
    )
    p.add_argument(
        "--features-dir",
        type=Path,
        required=True,
        help="Directory of {trace_id}.json feature snapshots",
    )
    p.add_argument("--out", type=Path, default=Path("training_out"), help="Output directory")
    p.add_argument(
        "--strict-labels",
        action="store_true",
        help="Require trace_id, tenant_id, label on each row",
    )
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    order = _feature_order()

    rows: list[dict[str, Any]] = []
    missing = 0
    skipped = 0
    for lab in _iter_label_objects(args.labels.read_text(encoding="utf-8")):
        if not isinstance(lab, dict):
            skipped += 1
            continue
        if args.strict_labels:
            bad = _validate_label_line(lab)
            if bad:
                print(f"skip invalid label row ({bad})")
                skipped += 1
                continue
        tid = lab.get("trace_id")
        if not tid:
            skipped += 1
            continue
        tid_s = str(tid)
        if not _TRACE_ID_RE.match(tid_s):
            print(f"skip unsafe trace_id: {tid_s!r}")
            skipped += 1
            continue
        feat_dir = args.features_dir.resolve()
        fp = feat_dir / f"{tid_s}.json"
        if fp.parent != feat_dir:
            skipped += 1
            continue
        if not fp.is_file():
            missing += 1
            continue
        feat = json.loads(fp.read_text(encoding="utf-8"))
        vec = _row_from_features(feat, order)
        y = 1 if str(lab.get("label", "")).lower() in ("fraud", "1", "true") else 0
        rows.append({"trace_id": tid_s, "y": y, **{order[i]: vec[i] for i in range(len(order))}})

    out_csv = args.out / "training_matrix.csv"
    if not rows:
        print(
            f"No rows built (missing feature files: {missing}, skipped: {skipped}). See contracts/training/label_row_v1.example.json",
        )
        return 1

    import csv

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["trace_id", "y"] + order)
        w.writeheader()
        w.writerows(rows)

    manifest = {
        "n_rows": len(rows),
        "missing_feature_snapshots": missing,
        "skipped_invalid_labels": skipped,
        "feature_columns": order,
        "feature_order_source": "ml_scoring.heuristic via scripts/ml/feature_order.py",
        "catalog_alignment": "payment_card_cnp_v1 / ml_scoring heuristic head",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out_csv} ({len(rows)} rows), manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
