#!/usr/bin/env python3
"""Memory pressure sentinel: track RSS for Orchestrator, Rule Engine, Shadow, and Ollama.

Uses ``psutil`` to sample process RSS concurrently (summed per logical role). Writes a **CSV**
time series. If combined stack RSS exceeds **20 GiB**, sends **SIGTERM** to matching **stress**
processes (``bench_ingestion.py`` / ``stress_test_ingestion.py`` by default) to shed load before
the host freezes.

Extra PIDs (e.g. a gate harness attributing a worker to ``ollama``)::

    python scripts/memory_guard.py --extra-track 12345:ollama

Requires ``psutil`` (``uv run --extra stress`` or ``pip install psutil``).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import signal
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

try:
    import psutil
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "psutil is required. Install with: pip install psutil\n"
        "Or from repo root: uv sync --extra stress\n"
    ) from exc

BYTES_IN_GIB = 1024**3
DEFAULT_THRESHOLD_BYTES = 20 * BYTES_IN_GIB
DEFAULT_STRESS_RE = r"(bench_ingestion|stress_test_ingestion)\.py"

# Cmdline / name heuristics (lowercased match).
_ORCH = ("orchestrator.main", "tarka-orchestrator", "/orchestrator/", "services/orchestrator")
_RULE = ("rule_engine.main", "tarka-rule-engine", "/rule_engine/", "services/rule_engine")
_SHADOW = ("shadow_agent", "shadow-agent", "/shadow_agent/", "services/shadow_agent")
_OLLAMA = ("ollama", "/ollama")


@dataclass(frozen=True)
class ExtraTrack:
    pid: int
    column: str  # orchestrator | rule_engine | shadow | ollama


def _cmdline(proc: psutil.Process) -> str:
    try:
        parts = proc.cmdline() or []
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return ""
    return " ".join(parts).lower()


def _classify_service(proc: psutil.Process, cmd: str) -> str | None:
    try:
        name = (proc.name() or "").lower()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None
    blob = f"{name} {cmd}"
    for m in _ORCH:
        if m in blob:
            return "orchestrator"
    for m in _RULE:
        if m in blob:
            return "rule_engine"
    for m in _SHADOW:
        if m in blob:
            return "shadow"
    for m in _OLLAMA:
        if m in blob:
            return "ollama"
    return None


def _rss_sum_for_service(service: str) -> int:
    total = 0
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            cmd = _cmdline(proc)
            if _classify_service(proc, cmd) != service:
                continue
            total += int(proc.memory_info().rss or 0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return total


def _rss_for_pid(pid: int) -> int:
    try:
        return int(psutil.Process(pid).memory_info().rss or 0)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0


def _stress_pids(pattern: re.Pattern[str]) -> list[int]:
    out: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            cmd = _cmdline(proc)
            if not cmd:
                continue
            if pattern.search(cmd):
                out.append(int(proc.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(set(out))


def _rss_stress(pattern: re.Pattern[str]) -> int:
    total = 0
    for pid in _stress_pids(pattern):
        total += _rss_for_pid(pid)
    return total


def _parse_extra_tracks(specs: Iterable[str]) -> list[ExtraTrack]:
    out: list[ExtraTrack] = []
    allowed = {"orchestrator", "rule_engine", "shadow", "ollama"}
    for raw in specs:
        if ":" not in raw:
            raise SystemExit(f"Invalid --extra-track (want pid:column): {raw!r}")
        a, b = raw.split(":", 1)
        pid = int(a.strip())
        col = b.strip().lower()
        if col not in allowed:
            raise SystemExit(f"--extra-track column must be one of {sorted(allowed)}, got {col!r}")
        out.append(ExtraTrack(pid=pid, column=col))
    return out


def _sample_row(
    stress_re: re.Pattern[str],
    extras: list[ExtraTrack],
) -> dict[str, float | int | str]:
    orch = _rss_sum_for_service("orchestrator")
    rule = _rss_sum_for_service("rule_engine")
    sh = _rss_sum_for_service("shadow")
    oll = _rss_sum_for_service("ollama")
    extras_by_col: dict[str, int] = defaultdict(int)
    for et in extras:
        extras_by_col[et.column] += _rss_for_pid(et.pid)
    orch_t = orch + extras_by_col["orchestrator"]
    rule_t = rule + extras_by_col["rule_engine"]
    sh_t = sh + extras_by_col["shadow"]
    oll_t = oll + extras_by_col["ollama"]
    stack = orch_t + rule_t + sh_t + oll_t
    stress = _rss_stress(stress_re)
    return {
        "utc_iso": datetime.now(UTC).isoformat(),
        "rss_orch_bytes": orch_t,
        "rss_re_bytes": rule_t,
        "rss_shadow_bytes": sh_t,
        "rss_ollama_bytes": oll_t,
        "rss_stress_bytes": stress,
        "rss_stack_bytes": stack,
        "rss_orch_mb": round(orch_t / (1024**2), 3),
        "rss_re_mb": round(rule_t / (1024**2), 3),
        "rss_shadow_mb": round(sh_t / (1024**2), 3),
        "rss_ollama_mb": round(oll_t / (1024**2), 3),
        "rss_stress_mb": round(stress / (1024**2), 3),
        "rss_stack_mb": round(stack / (1024**2), 3),
    }


def _write_csv_header(path: Path) -> None:
    new = not path.exists()
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)


def _append_csv(path: Path, row: dict[str, float | int | str], action: str) -> None:
    _write_csv_header(path)
    fieldnames = [
        "utc_iso",
        "rss_orch_mb",
        "rss_re_mb",
        "rss_shadow_mb",
        "rss_ollama_mb",
        "rss_stress_mb",
        "rss_stack_mb",
        "rss_orch_bytes",
        "rss_re_bytes",
        "rss_shadow_bytes",
        "rss_ollama_bytes",
        "rss_stress_bytes",
        "rss_stack_bytes",
        "action",
    ]
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        out = {k: row[k] for k in fieldnames if k != "action"}
        out["action"] = action
        w.writerow(out)


def main() -> int:
    p = argparse.ArgumentParser(description="RSS sentinel for orchestrator stack + CSV log.")
    p.add_argument("--csv", type=Path, default=Path("memory_guard_log.csv"), help="CSV output path")
    p.add_argument("--interval", type=float, default=1.0, help="Sample interval seconds")
    p.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds (0 = run until Ctrl+C)")
    p.add_argument("--threshold-gib", type=float, default=20.0, help="Stack RSS threshold in GiB")
    p.add_argument("--stress-regex", default=DEFAULT_STRESS_RE, help="Regex against full cmdline for stress PIDs")
    p.add_argument(
        "--no-kill-stress",
        action="store_true",
        help="Do not SIGTERM stress processes when over threshold (log only)",
    )
    p.add_argument(
        "--extra-track",
        action="append",
        default=[],
        metavar="PID:COLUMN",
        help="Add PID RSS into COLUMN (orchestrator|rule_engine|shadow|ollama). Repeatable.",
    )
    args = p.parse_args()
    stress_re = re.compile(args.stress_regex)
    extras = _parse_extra_tracks(args.extra_track)
    threshold = int(float(args.threshold_gib) * BYTES_IN_GIB)
    killed_once: set[int] = set()

    print(
        f"Memory guard → CSV {args.csv.resolve()}  interval={args.interval}s  "
        f"threshold_stack={args.threshold_gib}GiB  stress_regex={args.stress_regex!r}",
        flush=True,
    )

    t0 = time.monotonic()
    try:
        while True:
            row = _sample_row(stress_re, extras)
            stack_b = int(row["rss_stack_bytes"])
            action = "sample"
            if stack_b > threshold and not args.no_kill_stress:
                targets = [pid for pid in _stress_pids(stress_re) if pid not in killed_once]
                for pid in targets:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        killed_once.add(pid)
                        action = "SIGTERM_STRESS"
                        print(f"THRESHOLD: stack {stack_b} bytes > {threshold}; SIGTERM pid={pid}", flush=True)
                    except ProcessLookupError:
                        continue
                    except PermissionError as exc:
                        print(f"WARN: cannot SIGTERM pid={pid}: {exc}", file=sys.stderr, flush=True)
            _append_csv(args.csv, row, action)

            if args.duration > 0 and (time.monotonic() - t0) >= args.duration:
                break
            time.sleep(max(0.05, float(args.interval)))
    except KeyboardInterrupt:
        print("Stopped by user.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
