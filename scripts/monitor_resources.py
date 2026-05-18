#!/usr/bin/env python3
"""Sample CPU and RSS for Orchestrator, Rule Engine, Shadow, and local Ollama (``psutil``).

Writes a **CSV row every 5 seconds** (configurable) with per-role CPU% (aggregate of matching PIDs)
and RSS in MiB. Tracks **peak aggregate RSS** across the four roles (``Peak Memory Pressure``).

**MEMORY_CRITICAL**: printed to **stderr** whenever the **sum of RSS** for matched processes exceeds
**20 GiB** (``20 * 1024**3`` bytes), leaving ~4 GiB headroom on a 24 GiB machine.

Typical usage (two terminals)::

    # Terminal 1
    python3 scripts/monitor_resources.py --output tarka_resources.csv

    # Terminal 2
    python3 scripts/stress_test_ingestion.py

Install: ``pip install 'tarka[stress]'`` (includes ``psutil``) or ``pip install 'psutil>=6'``.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import os
import signal
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TextIO

try:
    import psutil
except ImportError as exc:  # pragma: no cover
    print(
        "monitor_resources: psutil is required. Install with:\n"
        "  pip install 'tarka[stress]'\n"
        "or:\n"
        "  pip install 'psutil>=6'",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


_MY_PID = os.getpid()
_BYTES_PER_GIB = 1024**3
_BYTES_PER_MIB = 1024 * 1024
_MEMORY_CRITICAL_BYTES = 20 * _BYTES_PER_GIB


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _split_patterns(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return tuple(p for p in parts if p)


def _cmdline(proc: psutil.Process) -> str:
    try:
        return " ".join(proc.cmdline() or ()).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _proc_name(proc: psutil.Process) -> str:
    try:
        return (proc.name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _matches_any(haystack: str, patterns: Iterable[str]) -> bool:
    return any(p.lower() in haystack for p in patterns if p)


@dataclass(frozen=True)
class RoleSpec:
    key: str
    csv_prefix: str
    patterns: tuple[str, ...]


def _resolve_processes(roles: list[RoleSpec]) -> dict[str, list[psutil.Process]]:
    """Assign each matched OS process to at most one role (first-role wins)."""
    assigned: dict[str, list[psutil.Process]] = {r.key: [] for r in roles}
    seen_pids: set[int] = set()

    for proc in psutil.process_iter():
        pid = proc.pid
        if pid == _MY_PID or pid in seen_pids:
            continue
        try:
            hay = f"{_cmdline(proc)} {_proc_name(proc)}"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        for spec in roles:
            if not _matches_any(hay, spec.patterns):
                continue
            assigned[spec.key].append(proc)
            seen_pids.add(pid)
            break

    return assigned


@contextlib.contextmanager
def _open_csv_output(path: str) -> Iterator[TextIO]:
    if path == "-":
        yield sys.stdout
    else:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            yield handle


def _flatten(by_role: dict[str, list[psutil.Process]]) -> list[psutil.Process]:
    out: list[psutil.Process] = []
    for plist in by_role.values():
        out.extend(plist)
    return out


def _prime_cpu(by_role: dict[str, list[psutil.Process]]) -> None:
    for proc in _flatten(by_role):
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


@dataclass
class MonitorState:
    peak_total_rss_bytes: int = 0
    memory_critical_events: int = 0
    samples: int = 0


def _collect_metrics(
    roles: list[RoleSpec],
    by_role: dict[str, list[psutil.Process]],
) -> tuple[dict[str, object], int]:
    """Read RSS and CPU% for each role. ``cpu_percent`` must have been primed ~interval earlier."""
    row: dict[str, object] = {}
    total_rss = 0

    for spec in roles:
        procs = by_role.get(spec.key, [])
        rss_sum = 0
        cpu_sum = 0.0
        for p in procs:
            try:
                rss = int(p.memory_info().rss)
                rss_sum += rss
                cpu_sum += float(p.cpu_percent(interval=None))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        row[f"{spec.csv_prefix}_cpu_pct"] = round(cpu_sum, 2)
        row[f"{spec.csv_prefix}_rss_mib"] = round(rss_sum / _BYTES_PER_MIB, 3)
        total_rss += rss_sum

    row["total_rss_mib"] = round(total_rss / _BYTES_PER_MIB, 3)
    row["memory_critical"] = 1 if total_rss > _MEMORY_CRITICAL_BYTES else 0
    return row, total_rss


def run_monitor(
    *,
    interval_s: float,
    out: TextIO,
    duration_s: float | None,
    roles: list[RoleSpec],
    state: MonitorState,
    stop_flag: list[bool],
) -> None:
    fieldnames = ["timestamp_iso"]
    for spec in roles:
        fieldnames.append(f"{spec.csv_prefix}_cpu_pct")
        fieldnames.append(f"{spec.csv_prefix}_rss_mib")
    fieldnames.extend(["total_rss_mib", "memory_critical"])

    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    out.flush()

    deadline = None if duration_s is None else time.monotonic() + float(duration_s)

    by_role = _resolve_processes(roles)
    _prime_cpu(by_role)

    while not stop_flag[0]:
        if deadline is not None and time.monotonic() >= deadline:
            break

        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(float(interval_s), remaining))
        else:
            time.sleep(float(interval_s))

        if stop_flag[0]:
            break
        if deadline is not None and time.monotonic() >= deadline:
            break

        by_role = _resolve_processes(roles)
        row, total_rss = _collect_metrics(roles, by_role)
        state.samples += 1

        if total_rss > state.peak_total_rss_bytes:
            state.peak_total_rss_bytes = total_rss

        row["timestamp_iso"] = _now_iso()
        if total_rss > _MEMORY_CRITICAL_BYTES:
            state.memory_critical_events += 1
            print("MEMORY_CRITICAL", file=sys.stderr, flush=True)

        writer.writerow(row)
        out.flush()

        _prime_cpu(by_role)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between CSV rows (default: 5).",
    )
    p.add_argument(
        "--output",
        "-o",
        default="-",
        help="CSV path, or '-' for stdout (default: '-').",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until SIGINT).",
    )
    p.add_argument(
        "--orchestrator-match",
        default=os.environ.get(
            "TARKA_MONITOR_ORCHESTRATOR",
            "orchestrator.main,/services/orchestrator",
        ),
        help="Comma/semicolon-separated substrings for orchestrator (env: TARKA_MONITOR_ORCHESTRATOR).",
    )
    p.add_argument(
        "--rule-match",
        default=os.environ.get("TARKA_MONITOR_RULE", "rule_engine.main,/services/rule_engine"),
        help="Match substrings for Rule Engine (env: TARKA_MONITOR_RULE).",
    )
    p.add_argument(
        "--shadow-match",
        default=os.environ.get("TARKA_MONITOR_SHADOW", "shadow_agent.main,/services/shadow_agent"),
        help="Match substrings for Shadow (env: TARKA_MONITOR_SHADOW).",
    )
    p.add_argument(
        "--ollama-match",
        default=os.environ.get("TARKA_MONITOR_OLLAMA", "ollama"),
        help="Match substrings for Ollama (env: TARKA_MONITOR_OLLAMA).",
    )
    args = p.parse_args(argv)

    roles = [
        RoleSpec("orchestrator", "orchestrator", _split_patterns(str(args.orchestrator_match))),
        RoleSpec("rule_engine", "rule_engine", _split_patterns(str(args.rule_match))),
        RoleSpec("shadow", "shadow", _split_patterns(str(args.shadow_match))),
        RoleSpec("ollama", "ollama", _split_patterns(str(args.ollama_match))),
    ]

    state = MonitorState()
    stop_flag = [False]

    def _on_signal(_signum: int, _frame: object | None) -> None:
        stop_flag[0] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    out_path = str(args.output)
    with _open_csv_output(out_path) as out:
        run_monitor(
            interval_s=float(args.interval),
            out=out,
            duration_s=args.duration,
            roles=roles,
            state=state,
            stop_flag=stop_flag,
        )

    peak_gib = state.peak_total_rss_bytes / _BYTES_PER_GIB
    print(
        f"Peak memory pressure (aggregate RSS of tracked processes): {peak_gib:.3f} GiB "
        f"({state.peak_total_rss_bytes} bytes over {state.samples} sample(s)); "
        f"MEMORY_CRITICAL rows/events: {state.memory_critical_events}.",
        file=sys.stderr,
    )
    if state.peak_total_rss_bytes > _MEMORY_CRITICAL_BYTES:
        print("MEMORY_CRITICAL", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
