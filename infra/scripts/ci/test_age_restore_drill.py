#!/usr/bin/env python3
"""CI contract for AGE Hunt restore drill + optional docker run."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "age_restore_drill.sh"


class TestAgeRestoreDrill(unittest.TestCase):
    def test_script_exists_and_executable_contract(self) -> None:
        self.assertTrue(_SCRIPT.is_file(), f"missing {_SCRIPT}")
        text = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("tar czf", text)
        self.assertIn("Person", text)
        self.assertIn("USES_DEVICE", text)
        self.assertIn("volume", text.lower())
        # Must not invoke logical restore (AGE OID break). Comment mentioning it is OK.
        self.assertNotRegex(text, r"(?m)^\s*pg_restore\b")
        self.assertNotRegex(text, r"(?m)^\s*pg_dump\b")

    def test_run_drill_when_docker_available(self) -> None:
        if os.environ.get("AGE_RESTORE_DRILL_SKIP") == "1":
            self.skipTest("AGE_RESTORE_DRILL_SKIP=1")
        if shutil.which("docker") is None:
            self.skipTest("docker not available")
        # Prefer explicit CI opt-in so default unit runs stay fast.
        if os.environ.get("AGE_RESTORE_DRILL_RUN") != "1":
            self.skipTest("set AGE_RESTORE_DRILL_RUN=1 to execute docker drill")
        r = subprocess.run(
            ["bash", str(_SCRIPT)],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("AGE restore drill OK", r.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
