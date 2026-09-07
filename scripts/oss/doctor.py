#!/usr/bin/env python3
"""Preflight for clone-and-run. No compose. CI-safe with mocks.

Run: python3 scripts/oss/doctor.py
Exit 0 only when Docker Compose v2 is on PATH, day-1 ports are free, and
host memory looks like the lite floor (~4 GB). Each fail names the fix.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Callable

DAY1_PORTS: tuple[int, ...] = (8000, 8001, 3000, 5432, 6379)
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


def port_messages(
    ports: tuple[int, ...] = DAY1_PORTS,
    *,
    check: PortCheck = port_is_free,
    probe_evaluate: EvaluateProbe | None = None,
) -> list[str]:
    lines: list[str] = []
    busy = [p for p in ports if not check(p)]
    if not busy:
        lines.append(f"[ok] ports free: {', '.join(str(p) for p in ports)}")
        return lines
    other = [p for p in busy if p != 8000]
    if other:
        listed = ", ".join(str(p) for p in other)
        lines.append(
            f"[fail] port in use: {listed} — stop the process bound there "
            "(host Postgres often owns 5432; host Redis often owns 6379). "
            "That is not a healthy Tarka evaluate. Then re-run make doctor."
        )
    if 8000 in busy:
        probe = probe_evaluate if probe_evaluate is not None else evaluate_health_ok
        if probe():
            lines.append(
                "[fail] port 8000 already serves GET /decisions/v1/health — "
                "a Tarka evaluate is up. make demo skips compose wait when that "
                f"probe succeeds. For a clean rebuild: docker compose -f {LITE_COMPOSE} down -v, "
                "then make doctor && make demo."
            )
        else:
            lines.append(
                "[fail] port 8000 is up but GET /decisions/v1/health failed — "
                "stale lite (no /decisions routes) or a non-Tarka process. "
                "Do not treat this as a healthy Tarka stack. "
                f"docker compose -f {LITE_COMPOSE} down -v, then make doctor && make demo."
            )
    return lines


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
