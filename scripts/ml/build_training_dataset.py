#!/usr/bin/env python3
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

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Keep in sync with services/ml-scoring/src/ml_scoring/heuristic.py
FEATURE_ORDER = [
    "amount",
    "hour_of_day",
    "is_new_device",
    "is_vpn",
    "is_emulator",
    "is_bot",
    "transaction_count_24h",
    "distinct_countries_7d",
    "account_age_days",
]


def _row_from_features(feat: dict[str, Any]) -> list[float | int]:
    out: list[float | int] = []
    for k in FEATURE_ORDER:
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


def main() -> int:
    p = argparse.ArgumentParser(description="Build ML training matrix from labels + feature snapshots")
    p.add_argument("--labels", type=Path, required=True, help="JSONL file; one label object per line")
    p.add_argument("--features-dir", type=Path, required=True, help="Directory of {trace_id}.json feature snapshots")
    p.add_argument("--out", type=Path, default=Path("training_out"), help="Output directory")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    missing = 0
    for line in args.labels.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        lab = json.loads(line)
        tid = lab.get("trace_id")
        if not tid:
            continue
        fp = args.features_dir / f"{tid}.json"
        if not fp.is_file():
            missing += 1
            continue
        feat = json.loads(fp.read_text(encoding="utf-8"))
        vec = _row_from_features(feat)
        y = 1 if str(lab.get("label", "")).lower() in ("fraud", "1", "true") else 0
        rows.append({"trace_id": tid, "y": y, **{FEATURE_ORDER[i]: vec[i] for i in range(len(FEATURE_ORDER))}})

    out_csv = args.out / "training_matrix.csv"
    if not rows:
        print(f"No rows built (missing feature files: {missing}). See contracts/training/label_row_v1.example.json")
        return 1

    import csv

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["trace_id", "y"] + FEATURE_ORDER)
        w.writeheader()
        w.writerows(rows)

    manifest = {
        "n_rows": len(rows),
        "missing_feature_snapshots": missing,
        "feature_columns": FEATURE_ORDER,
        "catalog_alignment": "payment_card_cnp_v1 / ml_scoring heuristic head",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out_csv} ({len(rows)} rows), manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
