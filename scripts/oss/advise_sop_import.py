#!/usr/bin/env python3
"""Air-gap Advise SOP / tenant OKF import.

Unzip → staging → validate_okf_bundle --scope tenant (exit 0) → stage under
OKF_TENANT_OVERLAYS_PATH/<tenant-id> for a read-only investigation-agent mount.

Never writes tenant SOP payloads into git. knowledge/tenants/ is an operator
mount (README only in the repo). Confluence / Wiki sync is later.

Usage (repo root)::

  python3 scripts/oss/advise_sop_import.py --zip tenant.zip --tenant-id t1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_VALIDATE = Path("services") / "investigation-agent" / "scripts" / "validate_okf_bundle.py"
_VALIDATE_SRC = Path("services") / "investigation-agent" / "src"
_OPERATOR_MOUNT = Path("knowledge") / "tenants"
_SKIP_DIRS = frozenset({"__MACOSX"})
# Path-safe tenant directory name. Rejects ../, slashes, and empty.
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def default_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parents[2], Path.cwd()):
        if (candidate / _VALIDATE).is_file():
            return candidate
    return here.parents[2]


def normalize_tenant_id(tenant_id: str) -> str:
    value = tenant_id.strip()
    if not _TENANT_ID.fullmatch(value):
        raise ValueError("tenant-id must be 1–128 chars [A-Za-z0-9._-] (not a path)")
    return value


def overlays_path_is_safe(overlays: Path, repo_root: Path) -> bool:
    """In-repo dest must be the operator mount. Outside the repo is fine."""
    try:
        rel = overlays.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return True
    return rel == _OPERATOR_MOUNT


def find_bundle_root(extracted: Path, tenant_id: str) -> Path:
    candidates = [
        extracted,
        extracted / tenant_id,
        extracted / "tenants" / tenant_id,
    ]
    children = [
        path
        for path in extracted.iterdir()
        if path.is_dir() and path.name not in _SKIP_DIRS and not path.name.startswith(".")
    ]
    if len(children) == 1:
        wrapper = children[0]
        candidates.extend((wrapper, wrapper / tenant_id, wrapper / "tenants" / tenant_id))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (candidate / "index.md").is_file():
            return candidate
    raise ValueError(f"no tenant OKF bundle root (index.md) for tenant-id {tenant_id!r} in extract")


def _zip_member_kind(info: zipfile.ZipInfo) -> str:
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        return "symlink"
    if info.is_dir() or stat.S_ISDIR(mode):
        return "dir"
    if mode and not stat.S_ISREG(mode):
        return "special"
    return "file"


def safe_extract(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with zipfile.ZipFile(zip_path) as handle:
        allowed: list[zipfile.ZipInfo] = []
        for info in handle.infolist():
            name = info.filename.replace("\\", "/")
            kind = _zip_member_kind(info)
            if kind in {"symlink", "special"}:
                raise ValueError(f"zip {kind} member rejected: {name}")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"zip path escapes staging: {name}")
            target = (dest / name).resolve()
            if not target.is_relative_to(dest_root):
                raise ValueError(f"zip path escapes staging: {name}")
            allowed.append(info)
        handle.extractall(dest, members=allowed)


def run_validate(
    *,
    bundle: Path,
    tenant_id: str,
    shared_root: Path | None,
    repo_root: Path,
) -> subprocess.CompletedProcess[str]:
    script = repo_root / _VALIDATE
    src = repo_root / _VALIDATE_SRC
    if not script.is_file():
        raise FileNotFoundError(f"validate_okf_bundle missing: {script}")
    env = os.environ.copy()
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(src) + (os.pathsep + prior if prior else "")
    cmd = [
        sys.executable,
        str(script),
        str(bundle),
        "--scope",
        "tenant",
        "--tenant-id",
        tenant_id,
    ]
    if shared_root is not None:
        cmd.extend(["--shared-root", str(shared_root)])
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


def stage_overlay(bundle: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.staging"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(bundle, tmp)
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)


def _resolve_staging(explicit: Path | None, tenant_id: str) -> Path:
    if explicit is not None:
        path = explicit / tenant_id
        path.mkdir(parents=True, exist_ok=True)
        return path
    env_base = (os.environ.get("OKF_STAGING_PATH") or "").strip()
    bases = [Path(env_base)] if env_base else [Path("/var/okf-staging")]
    for base in bases:
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / f".write-{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            path = base / f"{tenant_id}-{os.getpid()}"
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix=f"okf-{tenant_id}-"))


def import_sop(
    *,
    zip_path: Path,
    tenant_id: str,
    overlays: Path,
    repo_root: Path,
    staging: Path | None = None,
    shared_root: Path | None = None,
) -> dict[str, object]:
    tenant_id = normalize_tenant_id(tenant_id)
    if not zip_path.is_file():
        raise FileNotFoundError(f"zip not found: {zip_path}")
    if not overlays_path_is_safe(overlays, repo_root):
        raise ValueError(
            "in-repo overlays-path must be knowledge/tenants "
            "(operator mount; do not write tenant SOP payloads into git)"
        )
    overlays_root = overlays.resolve()
    dest = (overlays_root / tenant_id).resolve()
    if not dest.is_relative_to(overlays_root):
        raise ValueError("tenant dest escapes overlays-path")

    work = _resolve_staging(staging, tenant_id)
    extract_dir = work / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    safe_extract(zip_path, extract_dir)
    bundle = find_bundle_root(extract_dir, tenant_id)
    validated = run_validate(
        bundle=bundle,
        tenant_id=tenant_id,
        shared_root=shared_root,
        repo_root=repo_root,
    )
    if validated.returncode != 0:
        detail = (validated.stdout or validated.stderr or "validate_okf_bundle failed").strip()
        raise RuntimeError(
            f"validate_okf_bundle --scope tenant failed (exit {validated.returncode}): {detail}"
        )

    stage_overlay(bundle, dest)
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "overlays_path": str(overlays.resolve()),
        "dest": str(dest),
        "validate_exit": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a validated tenant OKF zip for Advise (air-gap bootstrap)."
    )
    parser.add_argument("--zip", type=Path, required=True, help="Tenant OKF zip")
    parser.add_argument("--tenant-id", required=True, help="Tenant id (validate --scope tenant)")
    parser.add_argument("--staging", type=Path, default=None, help="Staging directory")
    parser.add_argument(
        "--overlays-path",
        type=Path,
        default=None,
        help="Compose OKF_TENANT_OVERLAYS_PATH (default: env or knowledge/tenants)",
    )
    parser.add_argument(
        "--shared-root",
        type=Path,
        default=None,
        help="Approved shared OKF root for /shared/... links",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)

    repo_root = (args.repo_root or default_repo_root()).resolve()
    overlays = args.overlays_path
    if overlays is None:
        env_overlays = (os.environ.get("OKF_TENANT_OVERLAYS_PATH") or "").strip()
        overlays = Path(env_overlays) if env_overlays else repo_root / _OPERATOR_MOUNT
    shared = args.shared_root
    if shared is None:
        default_shared = repo_root / "knowledge" / "shared"
        shared = default_shared if default_shared.is_dir() else None

    try:
        payload = import_sop(
            zip_path=args.zip,
            tenant_id=args.tenant_id,
            overlays=overlays,
            repo_root=repo_root,
            staging=args.staging,
            shared_root=shared,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2))
    print(
        f"export OKF_TENANT_OVERLAYS_PATH={payload['overlays_path']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
