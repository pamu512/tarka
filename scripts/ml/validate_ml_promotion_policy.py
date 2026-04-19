#!/usr/bin/env python3
"""Validate shipped ONNX model metadata for promotion policy (OSS #37 / #52).

Rules:
- Every model version with traffic_weight > 0 must have training_metrics with auc_roc (when policy strict).
- Default: heuristic-v1 may omit auc (baseline); ONNX models must document auc_roc.

Exit 0 when all checks pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS = _REPO / "services" / "ml-scoring" / "models"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", type=Path, default=_DEFAULT_MODELS)
    p.add_argument(
        "--strict",
        action="store_true",
        help="Require auc_roc on every active version with traffic_weight > 0",
    )
    args = p.parse_args()
    root: Path = args.models_dir
    if not root.is_dir():
        print(f"models dir not found: {root}", file=sys.stderr)
        return 1
    errors: list[str] = []
    for model_dir in sorted(root.iterdir()):
        if not model_dir.is_dir():
            continue
        for ver_dir in sorted(model_dir.iterdir()):
            if not ver_dir.is_dir():
                continue
            meta_path = ver_dir / "metadata.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                errors.append(f"{meta_path}: {e}")
                continue
            tw = int(meta.get("traffic_weight", 0))
            if tw <= 0:
                continue
            name = str(meta.get("name") or model_dir.name)
            fw = str(meta.get("framework") or "").lower()
            tm = meta.get("training_metrics")
            if fw == "heuristic":
                continue
            if not isinstance(tm, dict) or tm.get("auc_roc") is None:
                msg = f"{name} v{ver_dir.name}: active weight {tw} but missing training_metrics.auc_roc"
                if args.strict:
                    errors.append(msg)
                else:
                    # ONNX / sklearn paths: require auc in repo samples
                    if "onnx" in fw or "sklearn" in fw or meta.get("algorithm"):
                        errors.append(msg)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: ML promotion metadata checks passed under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
