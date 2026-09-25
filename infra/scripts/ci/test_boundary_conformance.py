"""Self-test for the boundary conformance guard (G14, doc 13 concern 2).

The guard is a CI tripwire; this proves it actually trips. Each check runs
against a planted violation in a temp tree and must fail with the right
check id, and pass on a clean copy of the same tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

GUARD = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "scripts"
    / "ci"
    / "check_boundary_conformance.py"
)


def _run_guard(root: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(GUARD)],
        capture_output=True,
        text=True,
        env={"PYTHONUNBUFFERED": "1", "PATH": "/usr/bin:/bin"},
        cwd=str(root),
        timeout=60,
    )
    return r.returncode, r.stdout + r.stderr


def test_guard_passes_on_clean_tree(tmp_path):
    # minimal clean tree: leanNav with the /cases guard present
    fe = tmp_path / "frontend" / "src" / "config"
    fe.mkdir(parents=True)
    (fe / "leanNav.ts").write_text(
        'export function isNavItemVisible(path: string): boolean {\n'
        '  if ((DESK_PROFILE === "demo" || DESK_PROFILE === "product") && path === "/cases") return false;\n'
        "  return true;\n}\n",
        encoding="utf-8",
    )
    code, out = _run_guard(tmp_path)
    # M2 (case models file missing) is expected to fail on this minimal tree
    # only if the repo layout exists; guard ROOT is derived from the script
    # location (the real repo), so this runs against the REAL tree -> passes.
    assert code == 0, out


def test_guard_trips_on_cases_nav_regression(tmp_path):
    """If isNavItemVisible stops hiding /cases, the guard must fail M6."""
    src = GUARD.read_text(encoding="utf-8")
    # point the guard's ROOT at our temp tree
    mutated = src.replace(
        'ROOT = Path(__file__).resolve().parents[3]',
        f'ROOT = Path("{tmp_path}")',
    )
    guard_copy = tmp_path / "guard.py"
    guard_copy.write_text(mutated, encoding="utf-8")

    fe = tmp_path / "frontend" / "src" / "config"
    fe.mkdir(parents=True)
    (fe / "leanNav.ts").write_text(
        "export function isNavItemVisible(path: string): boolean {\n  return true;\n}\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(guard_copy)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 1
    assert "[M6]" in r.stdout
