#!/usr/bin/env python3
"""G2 prod-on-k8s digest honesty / publish path.

Fails when a generated prod-on-k8s values file has an empty digest on an
enabled core image (coreApi, plus signalApi / investigationAgent when enabled).

Empty digest is a limitation / non-grade, not an immutable claim. Lite and demo
are not this path. Smoke helm template may still pass --allow-empty-digest.

Companion to G1 helm_prod_honesty.sh (warn-only on empty digest when present).
This script is the CI-required fail for the grade / publish path.

Run:
  python3 infra/scripts/ci/helm_prod_digest_honesty.py --self-check
  python3 infra/scripts/ci/helm_prod_digest_honesty.py --values FILE
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "infra/scripts/deploy/generate_cloud_values.py"
CHART = ROOT / "infra/deploy/helm/fraud-stack"

CORE = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SIGNAL = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
AGENT = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"


def _load_gen():
    spec = importlib.util.spec_from_file_location("generate_cloud_values", GEN)
    if spec is None or spec.loader is None:
        raise SystemExit(f"FAIL: cannot load {GEN}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_prod_on_k8s_values(text: str) -> bool:
    return "# Preset: prod-on-k8s" in text


def scan_values(path: Path) -> int:
    gen = _load_gen()
    text = path.read_text(encoding="utf-8")
    if not _is_prod_on_k8s_values(text):
        print(f"OK: {path}: not prod-on-k8s generate output (lite/demo/other skipped)")
        return 0
    missing = gen.empty_enabled_digests(text)
    if missing:
        print(
            f"FAIL: {path}: empty digest on enabled prod-on-k8s images: "
            + ", ".join(missing)
            + " (not immutable; --digest-map required for the grade / publish path)",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {path}: sha256 pins present for enabled core images")
    return 0


def _gen_cmd(out: Path, extra: list[str]) -> list[str]:
    return [
        sys.executable,
        str(GEN),
        "--preset",
        "prod-on-k8s",
        "--image-registry",
        "registry.example.com/tarka",
        "--db-url",
        "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
        "--redis-url",
        "rediss://elasticache:6379/0",
        "--output",
        str(out),
        *extra,
    ]


def self_check() -> int:
    with tempfile.TemporaryDirectory() as td:
        empty = Path(td) / "empty.values.yaml"
        pinned = Path(td) / "pinned.values.yaml"
        digest_map = Path(td) / "digests.map"
        digest_map.write_text(
            f"coreApi={CORE}\nsignalApi={SIGNAL}\ninvestigationAgent={AGENT}\n",
            encoding="utf-8",
        )

        empty_gen = subprocess.run(
            _gen_cmd(empty, ["--allow-empty-digest"]),
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if empty_gen.returncode != 0:
            print(empty_gen.stderr + empty_gen.stdout, file=sys.stderr)
            print("FAIL: --allow-empty-digest generate failed", file=sys.stderr)
            return 2
        if scan_values(empty) == 0:
            print("FAIL: empty digest values passed grade scan (gate is blind)", file=sys.stderr)
            return 1
        print("OK: empty digest failed grade scan")

        pinned_gen = subprocess.run(
            _gen_cmd(pinned, ["--digest-map", str(digest_map)]),
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if pinned_gen.returncode != 0:
            print(pinned_gen.stderr + pinned_gen.stdout, file=sys.stderr)
            print("FAIL: --digest-map generate failed", file=sys.stderr)
            return 2
        if scan_values(pinned) != 0:
            print("FAIL: digest-map values failed grade scan", file=sys.stderr)
            return 1

        helm = shutil.which("helm")
        if helm:
            rendered = subprocess.run(
                [helm, "template", "tarka", str(CHART), "-f", str(pinned)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if rendered.returncode != 0:
                print(rendered.stderr, file=sys.stderr)
                print("FAIL: helm template of digest-pinned values failed", file=sys.stderr)
                return 2
            if f"tarka-core-api@{CORE}" not in rendered.stdout:
                print("FAIL: helm template missing core-api@sha256 pin", file=sys.stderr)
                return 1
            if f"tarka-signal-api@{SIGNAL}" not in rendered.stdout:
                print("FAIL: helm template missing signal-api@sha256 pin", file=sys.stderr)
                return 1
            if f"tarka-investigation-agent@{AGENT}" not in rendered.stdout:
                print("FAIL: helm template missing investigation-agent@sha256 pin", file=sys.stderr)
                return 1
            print("OK: helm template renders @sha256 pins")
        else:
            print("WARN: helm not on PATH; skipped template pin check", file=sys.stderr)

    print("OK: helm_prod_digest_honesty self-check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--values", help="Generated Helm values file to scan")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        return self_check()
    if not args.values:
        parser.error("pass --values FILE or --self-check")
    path = Path(args.values)
    if not path.is_file():
        raise SystemExit(f"FAIL: values file not found: {path}")
    return scan_values(path)


if __name__ == "__main__":
    raise SystemExit(main())
