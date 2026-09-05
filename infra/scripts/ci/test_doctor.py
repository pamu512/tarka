#!/usr/bin/env python3
"""Offline tests for scripts/oss/doctor.py (stdlib)."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_OSS = _REPO / "scripts" / "oss"
if str(_OSS) not in sys.path:
    sys.path.insert(0, str(_OSS))

import doctor  # noqa: E402


class TestDoctor(unittest.TestCase):
    def test_docker_missing_names_fix(self) -> None:
        ok, line = doctor.docker_on_path(which=lambda _n: None)
        self.assertFalse(ok)
        self.assertIn("Docker Desktop", line)
        self.assertIn("make doctor", line)

    def test_busy_port_names_fix(self) -> None:
        lines = doctor.port_messages(check=lambda p: p != 5432)
        text = "\n".join(lines)
        self.assertIn("[fail]", text)
        self.assertIn("5432", text)
        self.assertIn("Postgres", text)

    def test_free_ports_ok(self) -> None:
        lines = doctor.port_messages(check=lambda _p: True)
        self.assertTrue(lines[0].startswith("[ok]"))

    def test_low_ram_fails(self) -> None:
        ok, line = doctor.ram_message(mem_bytes=2 * 1024 * 1024 * 1024)
        self.assertFalse(ok)
        self.assertIn("4 GB", line)

    def test_run_doctor_green_path(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.run_doctor(
                check_port=lambda _p: True,
                mem_bytes=16 * 1024 * 1024 * 1024,
            )
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("[ok] doctor", out)
        self.assertNotIn("Unit21", out)
        self.assertNotIn("Sardine", out)


if __name__ == "__main__":
    unittest.main()
