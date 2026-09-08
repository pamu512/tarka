#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

"""Smoke-check cloud preset generation for Helm values."""

PRESETS = (
    "core-on-aws",
    "investigation-on-aws",
    "core-on-gcp",
    "full-on-k8s",
    "prod-on-k8s",
    "enterprise-desk-on-k8s",
)
SCRIPT = Path("infra/scripts/deploy/generate_cloud_values.py")
OUTPUT_DIR = Path("infra/deploy/generated")


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
    if preset == "prod-on-k8s":
        # Smoke render only. Empty digest is a limitation / non-grade.
        cmd.append("--allow-empty-digest")
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
    digest_script = Path("infra/scripts/ci/test_helm_image_digests.py")
    subprocess.run([sys.executable, str(digest_script)], check=True)
    oidc_script = Path("infra/scripts/ci/test_helm_oidc_redis.py")
    subprocess.run([sys.executable, str(oidc_script)], check=True)
    digest_honesty = Path("infra/scripts/ci/test_generate_cloud_values_digests.py")
    subprocess.run([sys.executable, str(digest_honesty)], check=True)
    honesty_tests = Path("infra/scripts/ci/test_helm_prod_digest_honesty.py")
    subprocess.run([sys.executable, str(honesty_tests)], check=True)
    digest_gate = Path("infra/scripts/ci/helm_prod_digest_honesty.py")
    subprocess.run([sys.executable, str(digest_gate), "--self-check"], check=True)
    honesty = Path("infra/scripts/ci/helm_prod_honesty.sh")
    subprocess.run(["bash", str(honesty), "--self-check"], check=True)
    for extra in (
        Path("infra/scripts/ci/test_helm_networkpolicy.py"),
        Path("infra/scripts/ci/test_helm_servicemonitor.py"),
        Path("infra/scripts/ci/test_production_observability_guide.py"),
    ):
        subprocess.run([sys.executable, str(extra)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
