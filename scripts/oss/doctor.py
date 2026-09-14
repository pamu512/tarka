#!/usr/bin/env python3
"""Preflight for clone-and-run. No compose. CI-safe with mocks.

Run: python3 scripts/oss/doctor.py
Exit 0 only when Docker Compose v2 is on PATH, day-1 ports are free, and
host memory looks like the lite floor (~4 GB). Each fail names the fix.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Callable

DAY1_PORTS: tuple[int, ...] = (8000, 8001, 3000, 5432, 6379)
# Host port remaps honored by infra/deploy/docker-compose.lite.yml.
PORT_ENV_MAP: dict[int, tuple[str, str]] = {
    5432: ("TARKA_PG_PORT", "Postgres"),
    6379: ("TARKA_REDIS_PORT", "Redis"),
    8000: ("TARKA_CORE_PORT", "core-api"),
    8001: ("TARKA_GRAPH_PORT", "graph-service"),
    3000: ("TARKA_FRONTEND_PORT", "frontend"),
    4222: ("TARKA_NATS_PORT", "NATS"),
    8007: ("TARKA_DATA_PLANE_PORT", "data-plane"),
    8790: ("TARKA_ORCHESTRATOR_PORT", "orchestrator"),
}
# Advisory only: needed just for the optional async-ingest profile.
INGEST_PORTS: tuple[int, ...] = (4222, 8007, 8790)
RAM_FLOOR_BYTES = 4 * 1024 * 1024 * 1024
EVALUATE_HEALTH_URL = "http://127.0.0.1:8000/decisions/v1/health"
LITE_COMPOSE = "infra/deploy/docker-compose.lite.yml"
PortCheck = Callable[[int], bool]
EvaluateProbe = Callable[[], bool]


def docker_on_path(*, which: Callable[[str], str | None] = shutil.which) -> tuple[bool, str]:
    if which("docker"):
        return True, "[ok] docker on PATH"
    return (
        False,
        "[fail] docker not on PATH — install Docker Desktop (Compose v2), then re-run make doctor.",
    )


def compose_v2_hint() -> str:
    return "Need Docker Compose v2 (`docker compose`, not the standalone docker-compose binary)."


def port_is_free(port: int, *, host: str = "127.0.0.1") -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def evaluate_health_ok(*, url: str = EVALUATE_HEALTH_URL, timeout: float = 1.5) -> bool:
    """True only when GET /decisions/v1/health returns JSON status=ok."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode())
            return body.get("status") == "ok"
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, TimeoutError):
        return False


def effective_port(default_port: int, environ: dict[str, str] | None = None) -> int:
    """Resolve a default port through its TARKA_*_PORT override when set."""
    env = os.environ if environ is None else environ
    entry = PORT_ENV_MAP.get(default_port)
    if not entry:
        return default_port
    raw = env.get(entry[0], "").strip()
    try:
        return int(raw) if raw else default_port
    except ValueError:
        return default_port


def port_messages(
    ports: tuple[int, ...] = DAY1_PORTS,
    *,
    check: PortCheck = port_is_free,
    probe_evaluate: EvaluateProbe | None = None,
    environ: dict[str, str] | None = None,
) -> list[str]:
    lines: list[str] = []
    targets = [(p, effective_port(p, environ)) for p in ports]
    busy = [eff for _p, eff in targets if not check(eff)]
    if not busy:
        shown = ", ".join(str(eff) for _p, eff in targets if _p == eff)
        remapped = [f"{p}->{eff} ({PORT_ENV_MAP[p][0]})" for p, eff in targets if p != eff]
        lines.append(f"[ok] ports free: {shown}" + (f" [remapped: {', '.join(remapped)}]" if remapped else ""))
        return lines
    other = [p for p in busy if p != effective_port(8000, environ)]
    if other:
        listed = ", ".join(str(p) for p in other)
        hints: list[str] = []
        for p in other:
            entry = PORT_ENV_MAP.get(p)
            if entry:
                hints.append(f"{p} = {entry[1]} (remap with {entry[0]}=…)")
        hint_text = (" — " + "; ".join(hints)) if hints else ""
        lines.append(
            f"[fail] port in use: {listed}{hint_text}. "
            f"See what owns it: lsof -nP -iTCP:{other[0]} -sTCP:LISTEN. "
            "Stop that process, or remap Tarka to a free port via the TARKA_*_PORT "
            "vars in infra/deploy/env/community.env.example. "
            "That is not a healthy Tarka evaluate. Then re-run make doctor."
        )
    if effective_port(8000, environ) in busy:
        probe = probe_evaluate if probe_evaluate is not None else evaluate_health_ok
        if probe():
            lines.append(
                "[fail] port 8000 already serves GET /decisions/v1/health — "
                "a Tarka evaluate is up. make demo skips compose wait when that "
                "probe succeeds. For a clean rebuild: docker compose -f {LITE_COMPOSE} down -v, "
                "then make doctor && make demo.".format(LITE_COMPOSE=LITE_COMPOSE)
            )
        else:
            lines.append(
                "[fail] port 8000 is up but GET /decisions/v1/health failed — "
                "stale lite (no /decisions routes) or a non-Tarka process. "
                "Do not treat this as a healthy Tarka stack. "
                f"docker compose -f {LITE_COMPOSE} down -v, then make doctor && make demo."
            )
    return lines


def ingest_port_messages(
    ports: tuple[int, ...] = INGEST_PORTS,
    *,
    check: PortCheck = port_is_free,
    environ: dict[str, str] | None = None,
) -> list[str]:
    """Advisory check for the optional async-ingest profile (nats/data-plane/orchestrator)."""
    targets = [(p, effective_port(p, environ)) for p in ports]
    busy = [eff for _p, eff in targets if not check(eff)]
    if not busy:
        shown = ", ".join(str(eff) for _p, eff in targets)
        return [f"[ok] ingest ports free (optional --profile ingest): {shown}"]
    listed = ", ".join(str(p) for p in busy)
    return [
        f"[warn] ingest port in use: {listed} — only matters if you enable the "
        "optional async ingest plane (docker compose --profile ingest up). "
        "Remap with TARKA_NATS_PORT / TARKA_DATA_PLANE_PORT / TARKA_ORCHESTRATOR_PORT."
    ]


def _sysctl_mem_bytes() -> int | None:
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        return int(out)
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def ram_message(*, mem_bytes: int | None, floor: int = RAM_FLOOR_BYTES) -> tuple[bool, str]:
    if mem_bytes is None:
        return True, "[warn] could not read host RAM — lite desk wants ~4 GB free; continue at your own risk."
    if mem_bytes >= floor:
        gb = mem_bytes / (1024 * 1024 * 1024)
        return True, f"[ok] host memory ~{gb:.1f} GB (lite floor is ~4 GB)"
    return (
        False,
        "[fail] host memory below ~4 GB — close other apps or use a machine with more RAM, then re-run make doctor.",
    )


def run_doctor(*, check_port: PortCheck = port_is_free, mem_bytes: int | None | object = ...) -> int:
    failed = False
    ok, docker_line = docker_on_path()
    print(docker_line)
    if not ok:
        print(compose_v2_hint())
        failed = True
    for line in port_messages(check=check_port):
        print(line)
        if line.startswith("[fail]"):
            failed = True
    for line in ingest_port_messages(check=check_port):
        print(line)
    ram = _sysctl_mem_bytes() if mem_bytes is ... else mem_bytes
    ram_ok, ram_line = ram_message(mem_bytes=ram)  # type: ignore[arg-type]
    print(ram_line)
    if not ram_ok:
        failed = True
    if failed:
        print("[fail] doctor — fix the lines above, then: make doctor && make demo")
        return 1
    print("[ok] doctor — next: make demo")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Day-1 preflight (Docker, ports, RAM).")
    parser.parse_args()
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
