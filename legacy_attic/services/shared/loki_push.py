"""Optional Grafana Loki push for structured JSON log lines (FastAPI / structlog).

Enabled when ``TARKA_LOKI_PUSH_URL`` or ``LOKI_PUSH_URL`` points at Loki's push API
(typically ``http://127.0.0.1:3100/loki/api/v1/push``).

Uses the same JSON formatter as stdout so lines match ELK/Loki queries. Push runs on a
background thread with a bounded queue; overload drops lines and emits a rate-limited
diagnostic. HTTP POST uses bounded timeouts, retries with exponential backoff + jitter,
and surfaces exhaustion to stderr (auditable).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

# Bound queue and HTTP behavior (local dev–friendly; tune via env if needed).
_DEFAULT_QUEUE_MAX = 4096
_DEFAULT_PUSH_TIMEOUT_S = 5.0
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_BACKOFF_BASE_S = 0.08
_DEFAULT_BACKOFF_CAP_S = 3.0

_SHUTDOWN = object()


def _loki_push_url() -> str:
    return (os.environ.get("TARKA_LOKI_PUSH_URL") or os.environ.get("LOKI_PUSH_URL") or "").strip()


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw, 10)
    except ValueError:
        return default


class LokiJsonPushHandler(logging.Handler):
    """Format records like the primary JSON handler, enqueue non-blocking for Loki."""

    def __init__(
        self,
        *,
        service_name: str,
        formatter: logging.Formatter,
        q: queue.Queue[str | object],
    ) -> None:
        super().__init__(level=logging.NOTSET)
        self._service_name = service_name
        self.setFormatter(formatter)
        self._q = q
        self._drop_lock = threading.Lock()
        self._drop_count = 0
        self._last_drop_report = 0.0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record).rstrip("\n")
            self._q.put_nowait(line)
        except queue.Full:
            self._record_drop()
        except Exception:
            self.handleError(record)

    def _record_drop(self) -> None:
        with self._drop_lock:
            self._drop_count += 1
            now = time.monotonic()
            if now - self._last_drop_report > 60.0:
                n = self._drop_count
                self._drop_count = 0
                self._last_drop_report = now
                sys.stderr.write(
                    f"[loki_push] dropped {n} log line(s); queue full (service={self._service_name})\n"
                )


def _build_push_body(service_name: str, lines: list[str]) -> dict[str, Any]:
    base_ns = time.time_ns()
    stream = {"job": "tarka", "service": service_name, "component": "python"}
    values: list[list[str]] = []
    for i, line in enumerate(lines):
        ts = str(base_ns + i)
        values.append([ts, line])
    return {"streams": [{"stream": stream, "values": values}]}


def _post_with_retries(url: str, body: bytes) -> None:
    timeout_s = _env_float("TARKA_LOKI_HTTP_TIMEOUT_S", _DEFAULT_PUSH_TIMEOUT_S)
    max_attempts = _env_int("TARKA_LOKI_MAX_ATTEMPTS", _DEFAULT_MAX_ATTEMPTS)
    base = _env_float("TARKA_LOKI_BACKOFF_BASE_S", _DEFAULT_BACKOFF_BASE_S)
    cap = _env_float("TARKA_LOKI_BACKOFF_CAP_S", _DEFAULT_BACKOFF_CAP_S)

    last_err: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if code is not None and 200 <= int(code) < 300:
                    return
                body_preview = ""
                try:
                    body_preview = resp.read(512).decode("utf-8", errors="replace")
                except OSError:
                    body_preview = ""
                raise RuntimeError(f"loki_push_http_status_{code}: {body_preview}")
        except urllib.error.HTTPError as e:
            last_err = e
            if 400 <= e.code < 500 and e.code != 429:
                sys.stderr.write(
                    f"[loki_push] non-retryable HTTP {e.code} posting to Loki; giving up\n"
                )
                return
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as e:
            last_err = e

        if attempt >= max_attempts:
            break
        sleep_s = min(cap, base * (2 ** (attempt - 1)))
        jitter = random.uniform(0, sleep_s * 0.25)
        time.sleep(sleep_s + jitter)

    sys.stderr.write(f"[loki_push] exhausted retries posting to Loki url={url!r}: {last_err!r}\n")


def _worker_loop(
    url: str,
    service_name: str,
    q: queue.Queue[str | object],
    batch_max: int,
) -> None:
    pending: list[str] = []
    while True:
        try:
            item = q.get(timeout=0.25)
        except queue.Empty:
            item = None

        if item is _SHUTDOWN:
            break

        if isinstance(item, str):
            pending.append(item)

        should_flush = bool(pending) and (len(pending) >= batch_max or (item is None and pending))
        if should_flush:
            body = json.dumps(_build_push_body(service_name, pending)).encode("utf-8")
            _post_with_retries(url, body)
            pending.clear()

    if pending:
        body = json.dumps(_build_push_body(service_name, pending)).encode("utf-8")
        _post_with_retries(url, body)


def attach_loki_logging_if_configured(
    *,
    service_name: str,
    json_formatter: logging.Formatter,
    root: logging.Logger | None = None,
) -> tuple[threading.Thread, queue.Queue[str | object]] | None:
    """If Loki URL is set, add a handler + background worker."""
    url = _loki_push_url()
    if not url:
        return None

    if not url.startswith("http://") and not url.startswith("https://"):
        sys.stderr.write(f"[loki_push] invalid URL scheme (must be http/https): {url!r}\n")
        return None

    q_max = _env_int("TARKA_LOKI_QUEUE_MAX", _DEFAULT_QUEUE_MAX)
    batch_max = max(1, min(200, _env_int("TARKA_LOKI_BATCH_MAX", 50)))
    q: queue.Queue[str | object] = queue.Queue(maxsize=q_max)

    handler = LokiJsonPushHandler(service_name=service_name, formatter=json_formatter, q=q)
    handler.setLevel(logging.DEBUG)
    (root or logging.getLogger()).addHandler(handler)

    worker = threading.Thread(
        target=_worker_loop,
        name=f"loki-push-{service_name}",
        args=(url, service_name, q, batch_max),
        daemon=True,
    )
    worker.start()
    return (worker, q)


def signal_loki_shutdown(q: queue.Queue[str | object] | None) -> None:
    """Enqueue shutdown so the worker flushes and exits (best-effort)."""
    if q is None:
        return
    try:
        q.put_nowait(_SHUTDOWN)
    except queue.Full:
        sys.stderr.write("[loki_push] queue full; shutdown signal dropped\n")
