"""
Locust stress harness for ``POST /v1/signals/ingest`` (~**1,000 RPS** target).

Install::

    pip install -e ".[load]"

Run (headless; ``--run-time`` is honored by :class:`IngestStressShape` as a cap alongside ``STRESS_SHAPE_DURATION_SEC``)::

    cd services/signal-api
    locust -f tests/load/stress_ingest.py --host=http://127.0.0.1:8788 \\
      --headless -t 120s --only-summary

Tune ``STRESS_SHAPE_USERS`` / ``STRESS_SHAPE_SPAWN_RATE`` (or run distributed Locust) until the reported RPS is near
**1,000** on your stack.

Optional **gates** (exit non-zero if violated; see env vars below)::

    STRESS_INGEST_ENFORCE_GATES=1 \\
    STRESS_MONITOR_PID=<uvicorn-or-gunicorn-pid> \\
    locust -f tests/load/stress_ingest.py --host=http://127.0.0.1:8788 --headless -t 120s

**Latency gate**: Locust records **end-to-end** HTTP response time in **milliseconds**. With
``STRESS_INGEST_ENFORCE_GATES=1``, **p99** must stay **strictly below** ``STRESS_MAX_LATENCY_MS`` (default ``10``).
Use localhost and a warmed server; real WAN will not meet a 10 ms bar.

**RAM gate**: With ``STRESS_MONITOR_PID`` set to the **signal-api** (or other) Python process, peak RSS minus a
short baseline sample must stay **below** ``STRESS_MAX_RAM_OVERHEAD_BYTES`` (default ``1_073_741_824`` = 1 GiB).
If unset, the gate uses the **current Locust process** (usually not what you want for server overhead).

Environment
-----------

``STRESS_TARGET_RPS``           Documentation hint only (default ``1000``); tune ``STRESS_SHAPE_*`` to approach it.

``STRESS_INGEST_PATH``        URL path (default ``/v1/signals/ingest``).

``STRESS_INGEST_ENFORCE_GATES``  Set to ``1`` to enable exit-code checks on stop.

``STRESS_MAX_LATENCY_MS``     p99 ceiling for gate (default ``10``).

``STRESS_MAX_RAM_OVERHEAD_BYTES``  RSS growth ceiling (default ``1073741824``).

``STRESS_MONITOR_PID``        PID whose RSS is sampled (recommended: server PID).

``STRESS_SHAPE_USERS``        ``LoadTestShape`` user count (default ``250``).

``STRESS_SHAPE_SPAWN_RATE``   Users spawned per second (default ``50``).

``STRESS_SHAPE_DURATION_SEC`` Upper bound on run length in seconds (default ``120``); capped by ``--run-time`` when
                              both are set (minimum wins).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from locust import HttpUser, LoadTestShape, between, events, task

logger = logging.getLogger(__name__)

_INGEST_PATH = (os.environ.get("STRESS_INGEST_PATH") or "/v1/signals/ingest").strip() or "/v1/signals/ingest"
_peak_rss_lock = threading.Lock()
_peak_rss: int = 0
_baseline_rss: int = 0
_sampler_stop = threading.Event()
_sampler_thread: threading.Thread | None = None


def _parse_bool(raw: str | None) -> bool:
    if not raw:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _rss_sampler(pid: int) -> None:
    global _peak_rss
    try:
        import psutil
    except ImportError:
        logger.warning("psutil not installed; RAM gate will be skipped")
        return
    try:
        proc = psutil.Process(pid)
    except psutil.Error as e:
        logger.warning("RAM sampler could not attach to pid=%s: %s", pid, e)
        return
    while not _sampler_stop.wait(0.25):
        try:
            rss = proc.memory_info().rss
            with _peak_rss_lock:
                if rss > _peak_rss:
                    _peak_rss = rss
        except psutil.Error:
            break


@events.test_start.add_listener
def _on_test_start(environment: Any, **kwargs: Any) -> None:
    global _baseline_rss, _peak_rss, _sampler_thread, _sampler_stop
    _sampler_stop.clear()
    _peak_rss = 0
    _baseline_rss = 0
    _sampler_thread = None

    try:
        import psutil
    except ImportError:
        return

    raw_pid = (os.environ.get("STRESS_MONITOR_PID") or "").strip()
    pid = int(raw_pid) if raw_pid else os.getpid()
    try:
        _baseline_rss = psutil.Process(pid).memory_info().rss
    except psutil.Error as e:
        logger.warning("Could not read baseline RSS for pid=%s: %s", pid, e)
        return

    with _peak_rss_lock:
        _peak_rss = _baseline_rss

    _sampler_thread = threading.Thread(target=_rss_sampler, args=(pid,), name="stress-rss-sampler", daemon=True)
    _sampler_thread.start()


@events.test_stop.add_listener
def _on_test_stop(environment: Any, **kwargs: Any) -> None:
    global _sampler_thread
    _sampler_stop.set()
    if _sampler_thread is not None:
        _sampler_thread.join(timeout=5.0)
        _sampler_thread = None


@events.quitting.add_listener
def _enforce_gates(environment: Any, **kwargs: Any) -> None:
    if not _parse_bool(os.environ.get("STRESS_INGEST_ENFORCE_GATES")):
        return

    stats = environment.stats.total
    if stats.num_requests == 0:
        logger.error("stress_gate_fail: zero requests recorded")
        environment.process_exit_code = 3
        return

    max_latency_ms = _parse_int("STRESS_MAX_LATENCY_MS", 10)
    p99 = stats.get_response_time_percentile(0.99)
    if p99 >= max_latency_ms:
        logger.error(
            "stress_gate_fail: p99 latency %s ms >= ceiling %s ms",
            p99,
            max_latency_ms,
        )
        environment.process_exit_code = 2

    max_overhead = _parse_int("STRESS_MAX_RAM_OVERHEAD_BYTES", 1_073_741_824)
    overhead = 0
    with _peak_rss_lock:
        overhead = max(0, _peak_rss - _baseline_rss)

    if _baseline_rss == 0:
        logger.warning("stress_gate_skip: RAM gate skipped (no baseline RSS; install psutil and set STRESS_MONITOR_PID)")
    elif overhead >= max_overhead:
        logger.error(
            "stress_gate_fail: RSS overhead %s bytes >= ceiling %s bytes (baseline=%s peak=%s)",
            overhead,
            max_overhead,
            _baseline_rss,
            _peak_rss,
        )
        environment.process_exit_code = max(environment.process_exit_code or 0, 4)

    if stats.num_failures > 0:
        logger.error("stress_gate_fail: failures=%s", stats.num_failures)
        environment.process_exit_code = max(environment.process_exit_code or 0, 5)


class IngestStressShape(LoadTestShape):
    """Ramp to a fixed user count for a bounded duration (tune users/spawn for ~1000 RPS)."""

    def tick(self) -> tuple[int, float] | None:
        max_sec = float(os.environ.get("STRESS_SHAPE_DURATION_SEC") or "120")
        opts = getattr(self.runner.environment, "parsed_options", None)
        rt = getattr(opts, "run_time", None) if opts is not None else None
        if rt is not None:
            if isinstance(rt, (int, float)):
                cli_sec = float(rt)
            else:
                from locust.util.timespan import parse_timespan

                try:
                    cli_sec = float(parse_timespan(str(rt)))
                except ValueError:
                    cli_sec = max_sec
            max_sec = min(max_sec, cli_sec)
        if self.get_run_time() > max_sec:
            return None
        users = _parse_int("STRESS_SHAPE_USERS", 250)
        spawn = float(os.environ.get("STRESS_SHAPE_SPAWN_RATE") or "50")
        return users, spawn


class IngestHttpUser(HttpUser):
    """POST unified ingest with a fresh ``sid`` each time (avoids Redis dedup 204)."""

    wait_time = between(0, 0)

    def _payload(self) -> dict[str, Any]:
        return {
            "ch": "c" * 64,
            "wv": "LocustStress",
            "dm": 8,
            "ip": "198.51.100.99",
            "px": False,
            "ua": "Mozilla/5.0 (stress; Locust)",
            "sid": str(uuid4()),
            "ts": datetime.now(UTC).isoformat(),
            "sv": "98.0.0",
            "mv": 0.0,
            "tp": 0,
            "hh": False,
        }

    @task(1)
    def post_ingest(self) -> None:
        self.client.post(_INGEST_PATH, json=self._payload(), name="ingest")
