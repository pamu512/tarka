#!/usr/bin/env python3
"""Self-test for scripts/audit_prod_desk_mocks.py lean desk rules (stdlib unittest)."""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from audit_prod_desk_mocks import main, scan_lean_desk_violations  # noqa: E402


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


class TestAuditProdDeskMocks(unittest.TestCase):
    def test_scan_flags_mockdata_import_in_lean_page(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "frontend/src/pages/Cases.tsx",
                'import { getMockResponse } from "../api/mockData";\n',
            )
            _write(
                root,
                "frontend/src/config/leanNav.ts",
                'export const LEAN_NAV_PATHS = new Set<string>(["/cases"]);\n',
            )
            errs = scan_lean_desk_violations(root)
            self.assertTrue(any("mockData" in e for e in errs), errs)

    def test_scan_flags_brochure_path_in_lean_nav(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(
                root,
                "frontend/src/config/leanNav.ts",
                """
                export const LEAN_NAV_PATHS = new Set<string>([
                  "/cases",
                  "/simulation",
                ]);
                """,
            )
            errs = scan_lean_desk_violations(root)
            self.assertTrue(any("/simulation" in e for e in errs), errs)

    def test_main_ok_on_real_repo(self) -> None:
        self.assertEqual(main(_REPO), 0)


if __name__ == "__main__":
    unittest.main()
