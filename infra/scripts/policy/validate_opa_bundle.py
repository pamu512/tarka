#!/usr/bin/env python3
"""Validate OPA policy bundles under infra/deploy/opa/ (Q1-E01 policy-as-code gate)."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_DEFAULT_BUNDLE = _REPO / "infra" / "deploy" / "opa"
_OPA_VERSION = os.environ.get("OPA_VERSION", "0.70.0")


def _opa_platform_slug() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return "darwin_arm64_static" if machine in {"arm64", "aarch64"} else "darwin_amd64"
    if system == "linux":
        return "linux_arm64_static" if machine in {"arm64", "aarch64"} else "linux_amd64"
    raise RuntimeError(f"unsupported platform for OPA download: {system}/{machine}")


def _ensure_opa_binary() -> Path:
    found = shutil.which("opa")
    if found:
        return Path(found)

    cache_dir = Path(tempfile.gettempdir()) / "tarka-opa"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"opa-{_OPA_VERSION}"
    if dest.is_file():
        return dest

    slug = _opa_platform_slug()
    url = f"https://openpolicyagent.org/downloads/v{_OPA_VERSION}/opa_{slug}"
    print(f"Downloading OPA v{_OPA_VERSION} ({slug}) …", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as resp, dest.open("wb") as out:
        out.write(resp.read())
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def _collect_rego(bundle_dir: Path) -> list[Path]:
    files = sorted(bundle_dir.rglob("*.rego"))
    if not files:
        raise FileNotFoundError(f"no .rego files under {bundle_dir}")
    return files


def _opa_check(opa: Path, bundle_dir: Path) -> None:
    cmd = [str(opa), "check", "--strict", str(bundle_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"opa check failed: {detail}")


def _opa_eval_smoke(opa: Path, bundle_dir: Path) -> None:
    """Evaluate infra/deploy/opa/policy.rego fraud.result with a minimal input envelope."""
    policy = bundle_dir / "policy.rego"
    if not policy.is_file():
        return
    text = policy.read_text(encoding="utf-8")
    if "package fraud" not in text:
        return

    query = "data.fraud.result"
    input_json = (
        '{"snapshot":{"tenant_id":"t1","entity_id":"e1","event_type":"payment",'
        '"features":{"country":"XX"},"redis_tags":[]}}'
    )
    cmd = [
        str(opa),
        "eval",
        "--format",
        "raw",
        "--data",
        str(bundle_dir),
        "-I",
        query,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, input=input_json)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"opa eval smoke failed: {detail}")
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError("opa eval smoke returned empty output")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=_DEFAULT_BUNDLE,
        help="Directory containing OPA .rego policies",
    )
    parser.add_argument(
        "--skip-eval-smoke",
        action="store_true",
        help="Skip data.fraud.result eval smoke (check only)",
    )
    args = parser.parse_args()
    bundle_dir = args.bundle_dir.resolve()
    if not bundle_dir.is_dir():
        print(f"bundle dir not found: {bundle_dir}", file=sys.stderr)
        return 1

    try:
        rego_files = _collect_rego(bundle_dir)
        opa = _ensure_opa_binary()
        _opa_check(opa, bundle_dir)
        if not args.skip_eval_smoke:
            _opa_eval_smoke(opa, bundle_dir)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"OK: validated OPA bundle ({len(rego_files)} rego file(s)) in {bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
