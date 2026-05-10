#!/usr/bin/env python3
"""Gate check: multithreaded memory spike + ``memory_guard`` CSV shows an Ollama-column spike.

Simulates **multi-threaded inference RSS** with a worker process that grows large buffers in
parallel threads. The parent runs ``memory_guard.py`` with ``--extra-track <worker_pid>:ollama`` so
the spike is attributed to the **ollama** CSV column (useful when no real Ollama binary is present).

Optionally runs ``scripts/bench_ingestion.py`` in parallel when ``--with-bench`` is set and
``ORCHESTRATOR_URL`` is configured.

Exit **0** if the Ollama column rises by at least ``--min-spike-mb`` between min and max over the run.
"""

from __future__ import annotations

import argparse
import csv
import os
import signal
import subprocess
import sys
import threading
import time
from multiprocessing import Event, Process, set_start_method
from pathlib import Path


def _spike_worker(mb_per_thread: int, go: Event) -> None:
    """Child process: wait for ``go``, then four threads each allocate ~mb_per_thread MiB."""
    go.wait(timeout=600)
    hold: list[bytearray] = []
    lock = threading.Lock()

    def grow() -> None:
        b = bytearray(mb_per_thread * 1024 * 1024)
        with lock:
            hold.append(b)

    threads = [threading.Thread(target=grow, name=f"infer-{i}", daemon=True) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Hold RSS until parent terminates this process.
    time.sleep(3600)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate: memory_guard logs multithreaded RSS spike.")
    ap.add_argument(
        "--min-spike-mb",
        type=float,
        default=150.0,
        help="Minimum Ollama-column swing (max-min) in MiB (default below 4×48MiB threads)",
    )
    ap.add_argument("--spike-mb-per-thread", type=int, default=48, help="MiB per inference thread (4 threads)")
    ap.add_argument("--guard-duration", type=float, default=12.0)
    ap.add_argument("--guard-interval", type=float, default=0.25)
    ap.add_argument(
        "--with-bench",
        action="store_true",
        help="Also run scripts/bench_ingestion.py if ORCHESTRATOR_URL is set",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    csv_path = repo_root / "artifacts" / "memory_guard_gate.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        csv_path.unlink()

    try:
        set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    go = Event()
    p_spike = Process(
        target=_spike_worker,
        args=(args.spike_mb_per_thread, go),
        name="llm_spike_sim",
    )
    p_spike.start()
    worker_pid = int(p_spike.pid or 0)
    if worker_pid <= 0:
        print("ERROR: spike worker has no pid", file=sys.stderr)
        return 2

    bench: subprocess.Popen[str] | None = None
    if args.with_bench and os.environ.get("ORCHESTRATOR_URL"):
        bench = subprocess.Popen(
            [sys.executable, str(repo_root / "scripts" / "bench_ingestion.py")],
            cwd=str(repo_root),
            env={**os.environ},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    guard_cmd = [
        sys.executable,
        str(repo_root / "scripts" / "memory_guard.py"),
        "--csv",
        str(csv_path),
        "--interval",
        str(args.guard_interval),
        "--duration",
        str(args.guard_duration),
        "--threshold-gib",
        "999",
        "--no-kill-stress",
        "--extra-track",
        f"{worker_pid}:ollama",
    ]
    guard = subprocess.Popen(guard_cmd, cwd=str(repo_root))
    # Baseline samples (worker idle), then release multithreaded allocation mid-trace.
    time.sleep(2.0)
    go.set()
    guard_rc = guard.wait()
    p_spike.terminate()
    p_spike.join(timeout=5)
    if p_spike.is_alive():
        p_spike.kill()
    if bench is not None:
        bench.send_signal(signal.SIGTERM)
        try:
            bench.wait(timeout=10)
        except subprocess.TimeoutExpired:
            bench.kill()

    if guard_rc != 0:
        print(f"WARN: memory_guard exited {guard_rc}", file=sys.stderr)

    if not csv_path.exists():
        print(f"ERROR: no CSV at {csv_path}", file=sys.stderr)
        return 3

    oll_vals: list[float] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                oll_vals.append(float(row["rss_ollama_mb"]))
            except (KeyError, ValueError):
                continue

    if len(oll_vals) < 3:
        print(f"ERROR: not enough CSV samples ({len(oll_vals)})", file=sys.stderr)
        return 4

    swing = max(oll_vals) - min(oll_vals)
    print(
        f"Gate: rss_ollama_mb min={min(oll_vals):.2f} max={max(oll_vals):.2f} "
        f"swing={swing:.2f} MiB (need >= {args.min_spike_mb})"
    )
    if swing < args.min_spike_mb:
        print("GATE_FAIL: expected multithreaded spike in rss_ollama_mb column", file=sys.stderr)
        return 1
    print("GATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
