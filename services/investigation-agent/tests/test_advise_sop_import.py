"""Operator SOP zip import: unzip → staging → validate_okf_bundle --scope tenant → overlay.

Tenant payloads stay off git. Dest is OKF_TENANT_OVERLAYS_PATH / tenant-id only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_IMPORT = _REPO_ROOT / "scripts" / "oss" / "advise_sop_import.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "okf"


def _zip_dir(src: Path, dest_zip: Path, *, arc_prefix: str = "") -> Path:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            arcname = f"{arc_prefix}{rel}" if arc_prefix else rel
            zf.write(path, arcname)
    return dest_zip


def _run_import(
    *,
    zip_path: Path,
    tenant_id: str,
    staging: Path,
    overlays: Path,
    shared_root: Path | None = None,
    extra: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_IMPORT),
        "--zip",
        str(zip_path),
        "--tenant-id",
        tenant_id,
        "--staging",
        str(staging),
        "--overlays-path",
        str(overlays),
        "--repo-root",
        str(_REPO_ROOT),
    ]
    if shared_root is not None:
        cmd.extend(["--shared-root", str(shared_root)])
    if extra:
        cmd.extend(extra)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=merged)


def test_import_script_exists() -> None:
    assert _IMPORT.is_file(), "scripts/oss/advise_sop_import.py is the operator zip bootstrap"


def test_valid_fixture_zip_stages_overlay_after_tenant_validate(tmp_path: Path) -> None:
    zip_path = _zip_dir(_FIXTURES / "tenants" / "t1", tmp_path / "t1.zip")
    staging = tmp_path / "staging"
    overlays = tmp_path / "overlays"
    result = _run_import(
        zip_path=zip_path,
        tenant_id="t1",
        staging=staging,
        overlays=overlays,
        shared_root=_FIXTURES / "shared",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    dest = overlays / "t1"
    assert payload["ok"] is True
    assert payload["validate_exit"] == 0
    assert payload["tenant_id"] == "t1"
    assert Path(payload["overlays_path"]) == overlays.resolve()
    assert Path(payload["dest"]) == dest.resolve()
    assert (dest / "index.md").is_file()
    assert (dest / "playbooks" / "high-amount-review.md").is_file()
    assert (dest / "source-manifest.json").is_file()
    # git operator mount stays empty in-repo; this dest is the compose overlay only
    assert not dest.resolve().is_relative_to((_REPO_ROOT / "knowledge" / "tenants").resolve())


def test_wrapped_tenant_dir_zip_finds_bundle_root(tmp_path: Path) -> None:
    zip_path = _zip_dir(
        _FIXTURES / "tenants" / "t1",
        tmp_path / "wrapped.zip",
        arc_prefix="t1/",
    )
    result = _run_import(
        zip_path=zip_path,
        tenant_id="t1",
        staging=tmp_path / "staging",
        overlays=tmp_path / "overlays",
        shared_root=_FIXTURES / "shared",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert ((tmp_path / "overlays" / "t1") / "index.md").is_file()


def test_invalid_bundle_does_not_stage_overlay(tmp_path: Path) -> None:
    bundle = tmp_path / "bad"
    bundle.mkdir()
    (bundle / "index.md").write_text('---\nokf_version: "0.1"\n---\n# bad\n', encoding="utf-8")
    (bundle / "playbooks").mkdir()
    (bundle / "playbooks" / "review.md").write_text(
        "---\ntype: Investigation Playbook\ntenant_scope: t1\n"
        "source_uri: playbooks/bad\nsource_content_hash: "
        + ("a" * 64)
        + "\napproval_status: proposed\napproved_revision: x\nsensitivity: internal\n---\nbody\n",
        encoding="utf-8",
    )
    zip_path = _zip_dir(bundle, tmp_path / "bad.zip")
    overlays = tmp_path / "overlays"
    result = _run_import(
        zip_path=zip_path,
        tenant_id="t1",
        staging=tmp_path / "staging",
        overlays=overlays,
        shared_root=_FIXTURES / "shared",
    )
    assert result.returncode != 0
    assert not (overlays / "t1").exists()


def test_zip_slip_is_rejected(tmp_path: Path) -> None:
    zip_path = tmp_path / "slip.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.md", "nope\n")
        zf.writestr("index.md", '---\nokf_version: "0.1"\n---\n')
    overlays = tmp_path / "overlays"
    result = _run_import(
        zip_path=zip_path,
        tenant_id="t1",
        staging=tmp_path / "staging",
        overlays=overlays,
        shared_root=_FIXTURES / "shared",
    )
    assert result.returncode != 0
    assert not (overlays / "t1").exists()
    assert "escape" in result.stderr.lower() or "zip" in result.stderr.lower()


def test_refuses_in_repo_dest_outside_operator_mount(tmp_path: Path) -> None:
    zip_path = _zip_dir(_FIXTURES / "tenants" / "t1", tmp_path / "t1.zip")
    result = _run_import(
        zip_path=zip_path,
        tenant_id="t1",
        staging=tmp_path / "staging",
        overlays=_REPO_ROOT / "docs",
        shared_root=_FIXTURES / "shared",
    )
    assert result.returncode != 0
    assert "knowledge/tenants" in result.stderr
    assert not (_REPO_ROOT / "docs" / "t1").exists()


def test_missing_zip_fails(tmp_path: Path) -> None:
    result = _run_import(
        zip_path=tmp_path / "missing.zip",
        tenant_id="t1",
        staging=tmp_path / "staging",
        overlays=tmp_path / "overlays",
    )
    assert result.returncode != 0
    assert "zip" in result.stderr.lower()
