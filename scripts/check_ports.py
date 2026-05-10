#!/usr/bin/env python3
"""Pre-flight port sentinel for Tarka host ports before ``docker compose`` brings up sidecars.

Uses the **socket** module to ``bind`` each port on the host. If ``bind`` raises ``EADDRINUSE``,
the port is not free. **psutil** then resolves the listening PID and process name; the script
prints a warning and exits **1** so startup can halt.

Default ports (Orchestrator, Rule Engine, Shadow) match the compose host mapping in this repo’s
beta layout: **8000**, **8001**, **8002**. Override with ``--port`` (repeatable).

Usage::

    python3 scripts/check_ports.py
    python3 scripts/check_ports.py --port 8000 --port 9000

Compose hook (example)::

    python3 scripts/check_ports.py && docker compose up -d

Requires **psutil** (``pip install psutil`` or ``uv sync --extra stress``).
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys


def _port_available(port: int) -> bool:
    """Return True only if the port can be bound on both wildcard and loopback.

    On some hosts, binding ``("", port)`` can succeed while another process holds
    ``127.0.0.1:port`` only; Docker publish still collides, so we test both.
    """
    for host in ("0.0.0.0", "127.0.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def _listener_info_lsof(port: int) -> tuple[int | None, str | None]:
    """Resolve listener PID when ``psutil`` cannot enumerate system-wide connections."""
    try:
        cp = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None, None
    if cp.returncode != 0 or not cp.stdout.strip():
        return None, None
    try:
        pid = int(cp.stdout.strip().splitlines()[0])
    except ValueError:
        return None, None
    try:
        ps = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            check=False,
        )
        name = (ps.stdout or "").strip() or None
    except OSError:
        name = None
    return pid, name


def _listener_info(port: int, psutil_mod: object) -> tuple[int | None, str | None]:
    """Best-effort PID and process name for a TCP LISTEN socket on ``port``."""
    # Per-process scan avoids macOS ``AccessDenied`` from ``psutil.net_connections()`` on some hosts.
    for proc in psutil_mod.process_iter(["pid", "name"]):
        pid = proc.info.get("pid")
        if pid is None:
            continue
        try:
            for conn in proc.net_connections(kind="inet"):
                if conn.status != psutil_mod.CONN_LISTEN:
                    continue
                if not conn.laddr or int(conn.laddr.port) != port:
                    continue
                return int(pid), proc.info.get("name")
        except (psutil_mod.AccessDenied, psutil_mod.NoSuchProcess):
            continue
    return _listener_info_lsof(port)


def main() -> int:
    try:
        import psutil
    except ImportError as exc:
        raise SystemExit(
            "psutil is required. Install with:\n"
            "  pip install psutil\n"
            "Or from repo root: uv sync --extra stress\n"
        ) from exc

    p = argparse.ArgumentParser(description="Verify Tarka host ports are free before compose up.")
    p.add_argument(
        "--port",
        action="append",
        type=int,
        dest="ports",
        metavar="N",
        help="Port to check (repeatable). Defaults: 8000 8001 8002",
    )
    args = p.parse_args()
    ports = args.ports if args.ports else [8000, 8001, 8002]

    conflicts: list[tuple[int, int | None, str | None]] = []
    for port in ports:
        if not _port_available(port):
            pid, pname = _listener_info(port, psutil)
            conflicts.append((port, pid, pname))

    if not conflicts:
        print(f"check_ports: OK — ports free: {', '.join(str(x) for x in ports)}", flush=True)
        return 0

    print("check_ports: BLOCKED — one or more Tarka ports are already in use on this host.", flush=True)
    for port, pid, pname in conflicts:
        who = f"{pname} (PID {pid})" if pid is not None and pname else (f"PID {pid}" if pid is not None else "unknown process")
        print(
            f"  Port {port}: in use by {who}. "
            "Stop that process or change the host port mapping in Docker Compose before starting Tarka.",
            flush=True,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
