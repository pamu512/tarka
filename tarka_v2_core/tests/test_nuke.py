"""Tests for ``tarka nuke`` (confirmation + SQLite deletion + compose invocation)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
import pytest
from typer.testing import CliRunner

from tarka_v2_core.cli import app


MINIMAL_COMPOSE = """\
name: tarka-nuke-test
services:
  placeholder:
    image: alpine:3.19
    command: ["true"]
"""


def test_nuke_aborts_on_n(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(MINIMAL_COMPOSE, encoding="utf-8")
    db = tmp_path / "audit.db"
    db.write_bytes(b"x")

    monkeypatch.setenv("DOCKER_COMPOSE_FILE", str(compose))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TARKA_NUKE_DATABASE_PATH", str(db))

    runner = CliRunner()
    result = runner.invoke(app, ["nuke"], input="N\n", env={**os.environ, "PYTHONPATH": str(tmp_path.parent.parent)})
    assert result.exit_code == 0
    assert db.is_file()
    assert "Aborted" in result.stdout


def test_nuke_deletes_sqlite_with_yes_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose = tmp_path / "compose.yml"
    compose.write_text(MINIMAL_COMPOSE, encoding="utf-8")
    db = tmp_path / "audit.db"
    db.write_bytes(b"sqlite")

    monkeypatch.setenv("DOCKER_COMPOSE_FILE", str(compose))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TARKA_NUKE_DATABASE_PATH", str(db))

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("tarka_v2_core.nuke.subprocess.run", fake_run)

    from tarka_v2_core.nuke import run_nuke

    repo_root = tmp_path
    _, deleted = run_nuke(
        repo_root=repo_root,
        compose_file=compose,
        compose_argv_prefix=["docker", "compose"],
        compose_runner=fake_run,
    )
    assert not db.exists()
    assert deleted == [db.resolve()]
    assert calls and "down" in calls[0]


def test_collect_paths_from_shadow_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "s.db"
    monkeypatch.setenv("SHADOW_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    from tarka_v2_core.nuke import collect_sqlite_database_paths

    paths = collect_sqlite_database_paths(tmp_path)
    assert db_path.resolve() in paths
