#!/usr/bin/env python3
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

"""Smoke-check cloud preset generation for Helm values."""

PRESETS = ("core-on-aws", "investigation-on-aws", "core-on-gcp", "full-on-k8s")
SCRIPT = Path("scripts/deploy/generate_cloud_values.py")
OUTPUT_DIR = Path("deploy/generated")


def _run_for_preset(preset: str) -> None:
    output_path = OUTPUT_DIR / f"{preset}.ci.values.yaml"
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--preset",
        preset,
        "--image-registry",
        "registry.example.com/tarka",
        "--db-url",
        "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
        "--redis-url",
        "redis://redis.internal:6379/0",
        "--output",
        str(output_path),
    ]
    subprocess.run(cmd, check=True)
    contents = output_path.read_text(encoding="utf-8")
    if "__" in contents:
        raise RuntimeError(f"Unresolved placeholder found in {output_path}")


def main() -> int:
    if not SCRIPT.exists():
        raise SystemExit(f"Missing script: {SCRIPT}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for preset in PRESETS:
        _run_for_preset(preset)
    print(f"Validated {len(PRESETS)} preset generations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
