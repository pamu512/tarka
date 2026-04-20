#!/usr/bin/env python3
"""Validate ML promotion policy files and shipped model metadata (OSS #37 / #52).

- Optional: ensure ml_promotion_policy_v1.json and .yaml stay in sync (requires PyYAML).
- Validate policy JSON schema (required keys / types).
- Check active ONNX/sklearn model versions under models/ have metadata matching policy strictness.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_MODELS = _REPO / "services" / "ml-scoring" / "models"
_POLICY_JSON = _REPO / "services" / "ml-scoring" / "rules" / "ml_promotion_policy_v1.json"


def _validate_policy_schema(policy: dict) -> list[str]:
    errs: list[str] = []
    if policy.get("policy_id") is None:
        errs.append("policy: missing policy_id")
    if policy.get("version") is None:
        errs.append("policy: missing version")
    for key in (
        "min_training_auc_roc",
        "max_training_latency_p99_ms",
        "max_fp_rate_delta_vs_champion",
        "min_recall_lift_vs_champion",
        "max_benchmark_latency_p95_ms",
    ):
        if key not in policy:
            errs.append(f"policy: missing key {key} (use null to disable)")
    return errs


def _check_models(root: Path, strict: bool) -> list[str]:
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
                if strict:
                    errors.append(msg)
                else:
                    if "onnx" in fw or "sklearn" in fw or meta.get("algorithm"):
                        errors.append(msg)
    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", type=Path, default=_DEFAULT_MODELS)
    p.add_argument(
        "--strict",
        action="store_true",
        help="Require auc_roc on every active version with traffic_weight > 0",
    )
    p.add_argument(
        "--check-sync",
        action="store_true",
        help="Require JSON/YAML policy files to parse identically (needs PyYAML)",
    )
    p.add_argument(
        "--policy-file",
        type=Path,
        default=_POLICY_JSON,
        help="Path to ml_promotion_policy_v1.json",
    )
    args = p.parse_args()

    if args.check_sync:
        sync_script = _REPO / "scripts" / "ml" / "check_ml_promotion_policy_sync.py"
        r = subprocess.run([sys.executable, str(sync_script)], cwd=_REPO)
        if r.returncode != 0:
            return r.returncode

    if not args.policy_file.is_file():
        print(f"policy file not found: {args.policy_file}", file=sys.stderr)
        return 1
    try:
        pol = json.loads(args.policy_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"{args.policy_file}: {e}", file=sys.stderr)
        return 1
    schema_errs = _validate_policy_schema(pol)
    if schema_errs:
        for e in schema_errs:
            print(e, file=sys.stderr)
        return 1

    root: Path = args.models_dir
    if not root.is_dir():
        print(f"models dir not found: {root}", file=sys.stderr)
        return 1
    errors = _check_models(root, args.strict)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: ML promotion policy + metadata checks passed under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
