#!/usr/bin/env python3
"""Regression tests for scripts/audit_stubs.py (runs in CI under lint job; stdlib unittest only)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "audit_stubs.py"


def _run_audit(services_root: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), str(services_root)],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout + r.stderr


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


class TestAuditStubs(unittest.TestCase):
    def test_fails_on_return_stub_dict(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = tmp / "services"
            _write(
                svc,
                "badapp/stub_api.py",
                '''
                def handler():
                    return {"status": "stub"}
                ''',
            )
            code, out = _run_audit(svc)
            self.assertEqual(code, 1, msg=out)
            self.assertIn("stub_api.py:", out)
            self.assertIn("status='stub'", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fails_on_raise_notimplemented(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = tmp / "services"
            _write(
                svc,
                "badapp/nope.py",
                '''
                def run():
                    raise NotImplementedError("later")
                ''',
            )
            code, out = _run_audit(svc)
            self.assertEqual(code, 1, msg=out)
            self.assertIn("nope.py:", out)
            self.assertIn("NotImplementedError", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fails_on_pass_only_body(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = tmp / "services"
            _write(
                svc,
                "badapp/empty.py",
                '''
                def todo():
                    pass
                ''',
            )
            code, out = _run_audit(svc)
            self.assertEqual(code, 1, msg=out)
            self.assertIn("empty.py:", out)
            self.assertRegex(out.lower(), "pass|\\.\\.\\.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allows_abstractmethod(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = tmp / "services"
            _write(
                svc,
                "goodapp/abc_ok.py",
                '''
                from abc import ABC, abstractmethod

                class Base(ABC):
                    @abstractmethod
                    def m(self):
                        raise NotImplementedError

                    @abstractmethod
                    def p(self):
                        pass
                ''',
            )
            code, out = _run_audit(svc)
            self.assertEqual(code, 0, msg=out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_allows_protocol_ellipsis(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            svc = tmp / "services"
            _write(
                svc,
                "goodapp/proto.py",
                '''
                from typing import Protocol

                class P(Protocol):
                    def f(self) -> int: ...
                ''',
            )
            code, out = _run_audit(svc)
            self.assertEqual(code, 0, msg=out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ok_on_real_repo_services(self) -> None:
        code, out = _run_audit(_REPO / "services")
        self.assertEqual(code, 0, msg=out)


if __name__ == "__main__":
    unittest.main()
