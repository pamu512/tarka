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

    def test_busy_8000_without_evaluate_is_not_healthy_tarka(self) -> None:
        lines = doctor.port_messages(
            check=lambda p: p != 8000,
            probe_evaluate=lambda: False,
        )
        text = "\n".join(lines)
        self.assertIn("[fail]", text)
        self.assertIn("/decisions/v1/health", text)
        self.assertIn("stale", text)
        self.assertNotIn("already up", text)

    def test_busy_8000_with_evaluate_names_rebuild(self) -> None:
        lines = doctor.port_messages(
            check=lambda p: p != 8000,
            probe_evaluate=lambda: True,
        )
        text = "\n".join(lines)
        self.assertIn("[fail]", text)
        self.assertIn("/decisions/v1/health", text)
        self.assertIn("already", text)
        self.assertIn("down -v", text)

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


    def test_busy_port_message_shows_lsof_and_remap(self) -> None:
        lines = doctor.port_messages(check=lambda p: p != 5432)
        text = "\n".join(lines)
        self.assertIn("lsof -nP -iTCP:5432", text)
        self.assertIn("TARKA_PG_PORT", text)

    def test_remapped_port_checked_instead_of_default(self) -> None:
        env = {"TARKA_PG_PORT": "15432"}
        # 5432 itself is busy but remapped away → must not appear as a failure.
        lines = doctor.port_messages(check=lambda p: p not in (5432, 15432), environ=env)
        text = "\n".join(lines)
        self.assertIn("15432", text)
        self.assertIn("[fail]", text)

    def test_remapped_free_default_busy_passes(self) -> None:
        env = {"TARKA_PG_PORT": "15432"}
        lines = doctor.port_messages(check=lambda p: p != 5432, environ=env)
        text = "\n".join(lines)
        self.assertTrue(any(l.startswith("[ok]") for l in lines), text)

    def test_ingest_ports_busy_warns_with_profile_hint(self) -> None:
        lines = doctor.ingest_port_messages(check=lambda p: p != 4222)
        self.assertTrue(lines[0].startswith("[warn]"), lines)
        self.assertIn("4222", lines[0])
        self.assertIn("profile ingest", lines[0])
        self.assertIn("TARKA_NATS_PORT", lines[0])

    def test_ingest_ports_free_ok(self) -> None:
        lines = doctor.ingest_port_messages(check=lambda _p: True)
        self.assertTrue(lines[0].startswith("[ok]"), lines)

    def test_run_doctor_warns_but_passes_on_busy_ingest_port(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = doctor.run_doctor(check_port=lambda p: p != 4222, mem_bytes=16 * 1024 * 1024 * 1024)
        self.assertEqual(code, 0)
        self.assertIn("[warn]", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
