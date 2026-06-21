#!/usr/bin/env python3
"""One-shot v1.3.0 monorepo layout migration (run from repo root)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (src_glob, dest_service, package_name to strip from imports)
FLATTEN_SERVICES = [
    ("tarka_v2_core/services/orchestrator", "services/orchestrator", "orchestrator"),
    ("tarka_v2_core/services/shadow_agent", "services/shadow_agent", "shadow_agent"),
    ("tarka_v2_core/services/rule_engine", "services/rule_engine", "rule_engine"),
    ("tarka_v2_core/services/signal-api", "services/signal-api", "signal_api"),
    ("tarka_v2_core/services/ingestor", "services/ingestor", "ingestor"),
]

V2_HOIST_AS_IS = [
    ("tarka_v2_core/services/shadow", "services/shadow"),
    ("tarka_v2_core/services/ml_sidecar", "services/ml_sidecar"),
]

LEGACY_SERVICES = "legacy_attic/services"

TEXT_EXTENSIONS = {
    ".py", ".toml", ".yml", ".yaml", ".md", ".json", ".sh", ".ts", ".tsx",
    ".js", ".mjs", ".rs", ".sql", ".ini", ".env", ".example", ".txt",
}


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def git_mv(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise SystemExit(f"dest exists: {dest}")
    run(["git", "mv", str(src.relative_to(ROOT)), str(dest.relative_to(ROOT))])


def flatten_service(v2_path: str, dest_path: str, package: str) -> None:
    src_root = ROOT / v2_path
    if not src_root.is_dir():
        print(f"skip missing {v2_path}")
        return
    dest = ROOT / dest_path
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    pkg_dir = src_root / "src" / package
    if not pkg_dir.is_dir():
        # already flat or different layout
        git_mv(src_root, dest)
        return

    # Copy service metadata
    for item in src_root.iterdir():
        if item.name in {"src", "__pycache__", ".pytest_cache", ".venv"}:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)

    # Flatten package code to service root
    for item in pkg_dir.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(pkg_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)

    rewrite_package_imports(dest, package)
    update_pyproject_flat(dest, package)
    update_dockerfile_flat(dest, package)
    shutil.rmtree(src_root)


def rewrite_package_imports(service_dir: Path, package: str) -> None:
    pkg_prefix = package.replace("-", "_")
    patterns = [
        (re.compile(rf"from {re.escape(pkg_prefix)}\."), "from "),
        (re.compile(rf"import {re.escape(pkg_prefix)}\."), "import "),
    ]
    alt = package.replace("_", "-")
    if alt != pkg_prefix:
        patterns.extend([
            (re.compile(rf"from {re.escape(alt)}\."), "from "),
            (re.compile(rf"import {re.escape(alt)}\."), "import "),
        ])

    for py in service_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        original = text
        for pat, repl in patterns:
            text = pat.sub(repl, text)
        # uvicorn module paths
        text = text.replace(f'"{pkg_prefix}.main:app"', '"main:app"')
        text = text.replace(f"'{pkg_prefix}.main:app'", "'main:app'")
        if text != original:
            py.write_text(text, encoding="utf-8")


def update_pyproject_flat(dest: Path, package: str) -> None:
    pyproject = dest / "pyproject.toml"
    if not pyproject.is_file():
        return
    text = pyproject.read_text(encoding="utf-8")
    text = re.sub(
        r'\[tool\.setuptools\.packages\.find\]\s*\nwhere = \["src"\]',
        '[tool.setuptools]\npy-modules = []\n\n[tool.setuptools.packages.find]\nwhere = ["."]',
        text,
    )
    text = text.replace('where = ["src"]', 'where = ["."]')
    text = re.sub(
        rf"^\s*{re.escape(package)}\s*=.*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Fix deploy-settings path depth (services/X is 2 levels from packages)
    text = text.replace("../../../packages/tarka-deploy-settings", "../../packages/deploy-settings")
    text = text.replace("../../../packages/deploy-settings", "../../packages/deploy-settings")
    pyproject.write_text(text, encoding="utf-8")


def update_dockerfile_flat(dest: Path, package: str) -> None:
    dockerfile = dest / "Dockerfile"
    if not dockerfile.is_file():
        return
    text = dockerfile.read_text(encoding="utf-8")
    text = text.replace("tarka_v2_core/", "")
    text = text.replace("/src", "")
    text = text.replace(f"{package}.main:app", "main:app")
    text = text.replace("services/ingestor/src", "services/ingestor")
    text = text.replace("services/rule_engine/src", "services/rule_engine")
    text = text.replace("packages/tarka-deploy-settings", "packages/deploy-settings")
    dockerfile.write_text(text, encoding="utf-8")


def hoist_legacy_services() -> None:
    legacy = ROOT / LEGACY_SERVICES
    if not legacy.is_dir():
        return
    for svc in sorted(legacy.iterdir()):
        if not svc.is_dir() or svc.name.startswith("."):
            continue
        dest = ROOT / "services" / svc.name
        if dest.exists():
            # Replace stub/partial with full legacy tree
            if dest.is_dir():
                shutil.rmtree(dest)
        git_mv(svc, dest)
        flatten_legacy_src(dest)


def flatten_legacy_src(dest: Path) -> None:
    src = dest / "src"
    if not src.is_dir():
        return
    # One package dir under src/
    children = [p for p in src.iterdir() if p.is_dir() and p.name != "__pycache__"]
    if len(children) != 1:
        return
    pkg = children[0]
    pkg_name = pkg.name.replace("-", "_")
    for item in pkg.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(pkg)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(item, target)
    rewrite_package_imports(dest, pkg_name)
    update_pyproject_flat(dest, pkg_name)
    if (dest / "Dockerfile").is_file():
        update_dockerfile_flat(dest, pkg_name)


def move_infra() -> None:
    deploy = ROOT / "deploy"
    infra = ROOT / "infra"
    if deploy.is_dir() and not (infra / "deploy").exists():
        infra.mkdir(parents=True, exist_ok=True)
        git_mv(deploy, infra / "deploy")

    for sub in ("deploy", "ci", "policy"):
        src = ROOT / "scripts" / sub
        if src.is_dir():
            dest = infra / "scripts" / sub
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                git_mv(src, dest)

    # Rename deploy-settings package
    old_pkg = ROOT / "packages" / "tarka-deploy-settings"
    new_pkg = ROOT / "packages" / "deploy-settings"
    if old_pkg.is_dir() and not new_pkg.exists():
        git_mv(old_pkg, new_pkg)
        pyproject = new_pkg / "pyproject.toml"
        if pyproject.is_file():
            text = pyproject.read_text(encoding="utf-8")
            text = text.replace('name = "tarka-deploy-settings"', 'name = "tarka-deploy-settings"')
            text = text.replace("tarka_deploy_settings", "tarka_deploy_settings")
            pyproject.write_text(text, encoding="utf-8")

    # Move tarka_shared into packages/shared-core
    shared_pkg = ROOT / "tarka_v2_core" / "services" / "shared"
    if shared_pkg.is_dir():
        dest = ROOT / "packages" / "shared-core"
        if not dest.exists():
            dest.mkdir(parents=True)
            shutil.copytree(shared_pkg / "tarka_shared", dest / "tarka_shared")
            for f in ("pyproject.toml", "alembic.ini"):
                if (shared_pkg / f).is_file():
                    shutil.copy2(shared_pkg / f, dest / f)
            if (shared_pkg / "alembic").is_dir():
                shutil.copytree(shared_pkg / "alembic", dest / "alembic")
            if (shared_pkg / "tests").is_dir():
                shutil.copytree(shared_pkg / "tests", dest / "tests")


def hoist_v2_misc() -> None:
    for src_rel, dest_rel in V2_HOIST_AS_IS:
        src = ROOT / src_rel
        dest = ROOT / dest_rel
        if src.is_dir() and not dest.exists():
            git_mv(src, dest)

    schemas = ROOT / "tarka_v2_core" / "schemas"
    if schemas.is_dir():
        dest = ROOT / "schemas"
        if not dest.exists():
            git_mv(schemas, dest)

    for name in ("cli.py", "rules_import.py"):
        src = ROOT / "tarka_v2_core" / name
        if src.is_file():
            dest = ROOT / name
            if not dest.exists():
                shutil.copy2(src, dest)


def bulk_replace_paths() -> None:
    replacements = [
        ("tarka_v2_core/services/orchestrator", "services/orchestrator"),
        ("tarka_v2_core/services/shadow_agent", "services/shadow_agent"),
        ("tarka_v2_core/services/rule_engine", "services/rule_engine"),
        ("tarka_v2_core/services/signal-api", "services/signal-api"),
        ("tarka_v2_core/services/ingestor", "services/ingestor"),
        ("tarka_v2_core/services/shared", "packages/shared-core"),
        ("tarka_v2_core/", ""),
        ("legacy_attic/services/", "services/"),
        ("legacy_attic/", ""),
        ("deploy/", "infra/deploy/"),
        ("scripts/deploy/", "infra/scripts/deploy/"),
        ("scripts/ci/", "infra/scripts/ci/"),
        ("scripts/policy/", "infra/scripts/policy/"),
        ("packages/tarka-deploy-settings", "packages/deploy-settings"),
        ("tarka-deploy-settings @ file:", "tarka-deploy-settings @ file:"),
        ("orchestrator.main:app", "main:app"),
        ("shadow_agent.main:app", "main:app"),
        ("rule_engine.main:app", "main:app"),
        ("signal_api.main:app", "main:app"),
    ]

    skip_dirs = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix not in TEXT_EXTENSIONS and path.name not in {"Dockerfile", "Makefile"}:
            continue
        if "restructure_v130_layout.py" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        original = text
        for old, new in replacements:
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")


def remove_empty_trees() -> None:
    for rel in ("tarka_v2_core", "legacy_attic"):
        p = ROOT / rel
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)


def main() -> None:
    move_infra()
    for v2, dest, pkg in FLATTEN_SERVICES:
        flatten_service(v2, dest, pkg)
    hoist_v2_misc()
    hoist_legacy_services()
    bulk_replace_paths()
    remove_empty_trees()
    print("Done. Review with: git status && git diff --stat")


if __name__ == "__main__":
    main()
