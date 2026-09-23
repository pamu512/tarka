#!/usr/bin/env python3
"""Named-pilot G9 soak start: backup + upgrade dry-run dating (not the grade)."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "soak_backup_upgrade_dry_run.py"
_BACKUP = _REPO / "infra" / "scripts" / "deploy" / "backup_restore_drill.sh"
_UPGRADE = _REPO / "docs" / "docs" / "guides" / "production-upgrade.md"
_VENDOR_RE = r"\b(Sift|Forter|Riskified|Feedzai|Featurespace)\b"


def _run(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("TARKA_BACKUP_DRILL_SKIP", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["python3", str(_SCRIPT), *args],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


class TestSoakBackupUpgradeDryRun(unittest.TestCase):
    def test_script_and_runbooks_exist(self) -> None:
        self.assertTrue(_SCRIPT.is_file(), f"missing {_SCRIPT.relative_to(_REPO)}")
        self.assertTrue(_BACKUP.is_file(), f"missing {_BACKUP.relative_to(_REPO)}")
        self.assertTrue(_UPGRADE.is_file(), f"missing {_UPGRADE.relative_to(_REPO)}")
        text = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--pilot-name", text)
        self.assertIn("--owner", text)
        self.assertIn("--date", text)
        self.assertIn("backup_restore_drill.sh", text)
        self.assertIn("production-upgrade.md", text)
        self.assertNotRegex(text, _VENDOR_RE)

    def test_blank_owner_exits_nonzero(self) -> None:
        r = _run("--pilot-name", "internal-lab", "--owner", "", "--date", "2026-09-22")
        self.assertNotEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertTrue("owner" in (r.stderr + r.stdout).lower())

    def test_blank_date_exits_nonzero(self) -> None:
        r = _run("--pilot-name", "internal-lab", "--owner", "lab-operator", "--date", "")
        self.assertNotEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertTrue("date" in (r.stderr + r.stdout).lower())

    def test_placeholder_owner_or_date_exits_nonzero(self) -> None:
        for owner, date in (("________", "2026-09-22"), ("lab-operator", "________"), ("   ", "2026-09-22")):
            r = _run("--pilot-name", "internal-lab", "--owner", owner, "--date", date)
            self.assertNotEqual(
                r.returncode,
                0,
                f"owner={owner!r} date={date!r} auto-passed:\n{r.stdout}\n{r.stderr}",
            )

    def test_blank_pilot_name_exits_nonzero(self) -> None:
        r = _run("--pilot-name", "   ", "--owner", "lab-operator", "--date", "2026-09-22")
        self.assertNotEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)

    def test_named_args_print_dated_g6_g7_evidence(self) -> None:
        r = _run(
            "--pilot-name",
            "internal-lab",
            "--owner",
            "lab-operator",
            "--date",
            "2026-09-22",
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        out = r.stdout
        lowered = out.lower()
        self.assertIn("internal-lab", out)
        self.assertIn("lab-operator", out)
        self.assertIn("2026-09-22", out)
        self.assertIn("g6", lowered)
        self.assertIn("g7", lowered)
        self.assertIn("dry-run OK", out)
        self.assertIn("production-upgrade.md", out)
        self.assertIn("backup_restore_drill", out)
        self.assertNotIn("GitLab-grade already achieved", out)
        self.assertNotIn("gitlab-grade claim: yes", lowered)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
