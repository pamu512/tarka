"""Destructive teardown for local v2 sidecars: compose down + optional SQLite audit DB removal."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

try:
    from sqlalchemy.engine.url import make_url
except ImportError:
    make_url = None  # type: ignore[misc, assignment]


class NukeError(RuntimeError):
    """Invalid configuration or failed subprocess during ``nuke``."""


def _sqlite_file_from_database_url(url: str) -> Path | None:
    """Return a host filesystem path if ``url`` is a file-backed SQLite URL."""
    if not url.strip() or ":memory:" in url:
        return None
    if make_url is None:
        return None
    try:
        u = make_url(url.strip())
    except Exception:
        return None
    name = (u.database or "").strip()
    if not name:
        return None
    driver = u.drivername or ""
    if "sqlite" not in driver:
        return None
    return Path(name)


def collect_sqlite_database_paths(repo_root: Path) -> list[Path]:
    """
    Paths to delete when nuking local audit storage.

    Sources (in order, deduped): ``TARKA_NUKE_DATABASE_PATH`` (comma-separated),
    ``SHADOW_DATABASE_URL``, ``TARKA_AUDIT_DATABASE_URL`` (if SQLite file URLs),
    and the conventional ``<repo>/.tarka/shadow.db``.
    """
    collected: list[Path] = []

    explicit = os.environ.get("TARKA_NUKE_DATABASE_PATH", "").strip()
    if explicit:
        for part in explicit.split(","):
            p = Path(part.strip()).expanduser()
            if p.parts:
                collected.append(p.resolve())

    for key in ("SHADOW_DATABASE_URL", "TARKA_AUDIT_DATABASE_URL"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        sp = _sqlite_file_from_database_url(raw)
        if sp is not None:
            collected.append(sp.resolve())

    collected.append((repo_root / ".tarka" / "shadow.db").resolve())

    seen: set[Path] = set()
    out: list[Path] = []
    for p in collected:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def run_nuke(
    *,
    repo_root: Path,
    compose_file: Path,
    compose_argv_prefix: list[str],
    compose_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    skip_compose: bool = False,
    remove_named_volumes: bool = False,
) -> tuple[list[str], list[Path]]:
    """
    Tear down compose stack (removes project containers and networks) and delete SQLite audit files.

    ``compose_argv_prefix`` is e.g. ``[\"docker\", \"compose\"]`` or ``[\"docker-compose\"]``.

    ``compose_runner`` defaults to ``subprocess.run`` (inject a stub in tests).

    Returns ``(docker_command_argv, paths_deleted)``.
    """
    run = compose_runner or subprocess.run
    cmd: list[str] = []
    if not skip_compose:
        if not compose_file.is_file():
            raise NukeError(f"Compose file not found: {compose_file}")
        cmd = compose_argv_prefix + ["-f", str(compose_file), "down", "--remove-orphans"]
        if remove_named_volumes:
            cmd.append("-v")
        cp = run(
            cmd,
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            err = (cp.stderr or cp.stdout or "").strip()
            raise NukeError(f"docker compose down failed ({cp.returncode}): {err[:500]}")

    deleted: list[Path] = []
    for path in collect_sqlite_database_paths(repo_root):
        try:
            if path.is_file():
                path.unlink()
                deleted.append(path)
        except OSError as exc:
            raise NukeError(f"Could not remove database file {path}: {exc}") from exc

    return (cmd, deleted)
