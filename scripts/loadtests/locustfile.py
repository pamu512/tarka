"""Proof pipeline load test — sustained HTTP evaluate + ClickHouse proof verification.

Simulates high decision throughput against ``POST /v1/decisions/evaluate``. After each successful
response, polls ClickHouse (default: ``fraud.fraud_decisions`` written by ``analytics-sink`` from
JetStream) until a row with the response ``trace_id`` appears — **within 2 seconds**. The stored
``trace_id`` is the same UUID string published on ``fraud.decisions.*``; treat it as the 128-bit
correlation id compatible with OpenTelemetry trace context.

**Prerequisites**

- Decision API reachable (``--host`` or ``LOCUST_HOST``).
- ``API_KEYS`` / ``x-api-key`` auth unless ``ALLOW_INSECURE_NO_AUTH`` is enabled server-side.
- NATS JetStream + **analytics-sink** consuming ``fraud.decisions.>`` and inserting into ClickHouse,
  or verification will fail after the 2s deadline.

**Target ~1 000 RPS**

Achieved RPS depends on decision-api latency and hardware. Start from ~``users ≈ target_rps * p95_latency_seconds``
with ``FastHttpUser`` and ``wait_time = 0``. Example::

    cd scripts/loadtests
    pip install -r requirements.txt
    locust -f locustfile.py --headless --host http://127.0.0.1:8005 \\
      -u 1200 -r 200 --run-time 5m --processes 4

Tune ``-u`` / ``-r`` while watching the Locust RPS chart until ~1000. Use ``ProofPipelineShape`` below
for a ramped profile.

Environment (optional overrides):

- ``CLICKHOUSE_HOST``, ``CLICKHOUSE_PORT`` (HTTP, default 8123), ``CLICKHOUSE_USER``,
  ``CLICKHOUSE_PASSWORD``, ``CLICKHOUSE_DATABASE`` (default ``fraud`` — matches analytics-sink).
- ``LOADTEST_CH_TABLE`` — table name only (default ``fraud_decisions``).
- ``LOADTEST_VERIFY_POSTGRES`` — ``1`` to assert ``decision_audit`` row (sync SQLAlchemy URL).
- ``LOADTEST_DATABASE_URL`` — Postgres URL for audit check (default: derive from ``DATABASE_URL``
  by stripping ``+asyncpg``).
- ``LOADTEST_VERIFY_REDIS`` — ``1`` to require ``redis`` PING in ``on_start``.
- ``LOADTEST_REDIS_URL`` — defaults to ``REDIS_URL``.
- ``LOADTEST_VERIFY_RUST_ENGINE`` — ``1`` to require ``import tarka_rule_engine`` in ``on_start``.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any
import gevent
from locust import LoadTestShape, constant, task
from locust.contrib.fasthttp import FastHttpUser

log = logging.getLogger("proof_pipeline_locust")

_POLL_INTERVAL_S = 0.05
_DEADLINE_S = 2.0


def _trace_id_valid_otel_correlation(trace_id: str) -> bool:
    """Accept W3C-style 32-hex trace id or RFC 4122 UUID string (decision-api format)."""
    s = trace_id.strip()
    if len(s) == 32:
        hex_part = s.lower()
        return all(c in "0123456789abcdef" for c in hex_part)
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False


def _sync_database_url_for_psycopg2(raw: str) -> str:
    u = raw.strip()
    if "+asyncpg" in u:
        return u.replace("postgresql+asyncpg://", "postgresql://", 1)
    return u


_ch_client: Any | None = None
_pg_engine: Any | None = None
_redis_client: Any | None = None


def _validate_sql_identifier(name: str) -> str:
    n = name.strip()
    if not n or not all(ch.isalnum() or ch == "_" for ch in n):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return n


def _clickhouse_client():
    global _ch_client
    if _ch_client is not None:
        return _ch_client
    import clickhouse_connect

    host = os.environ.get("CLICKHOUSE_HOST", "localhost")
    port = int(os.environ.get("CLICKHOUSE_HTTP_PORT") or os.environ.get("CLICKHOUSE_PORT") or "8123")
    user = os.environ.get("CLICKHOUSE_USER", "default")
    password = os.environ.get("CLICKHOUSE_PASSWORD") or ""
    database = os.environ.get("CLICKHOUSE_DATABASE", "fraud")
    secure = os.environ.get("CLICKHOUSE_SECURE", "").lower() in ("1", "true", "yes")
    connect_timeout = float(os.environ.get("CLICKHOUSE_CONNECT_TIMEOUT_S", "10"))
    send_receive_timeout = float(os.environ.get("CLICKHOUSE_QUERY_TIMEOUT_S", "30"))

    _ch_client = clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
        secure=secure,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )
    log.info(
        "clickhouse_connect client ready host=%s port=%s database=%s",
        host,
        port,
        database,
    )
    return _ch_client


def _postgres_engine():
    global _pg_engine
    if _pg_engine is not None:
        return _pg_engine
    from sqlalchemy import create_engine

    raw = (
        os.environ.get("LOADTEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if not raw:
        raise RuntimeError("LOADTEST_DATABASE_URL or DATABASE_URL required for Postgres verification")
    sync_url = _sync_database_url_for_psycopg2(raw)
    _pg_engine = create_engine(sync_url, pool_pre_ping=True, pool_size=2, max_overflow=0)
    return _pg_engine


def _redis_sync_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    import redis as redis_sync

    url = (os.environ.get("LOADTEST_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()
    if not url:
        raise RuntimeError("LOADTEST_REDIS_URL or REDIS_URL required for Redis verification")
    _redis_client = redis_sync.Redis.from_url(
        url,
        socket_connect_timeout=5.0,
        socket_timeout=5.0,
    )
    return _redis_client


def _verify_optional_infra_on_start() -> None:
    if os.environ.get("LOADTEST_VERIFY_REDIS", "").strip().lower() in ("1", "true", "yes", "on"):
        rc = _redis_sync_client()
        rc.ping()

    if os.environ.get("LOADTEST_VERIFY_RUST_ENGINE", "").strip().lower() in ("1", "true", "yes", "on"):
        import tarka_rule_engine as tre  # noqa: PLC0415

        tre.rust_engine_cache_stats()


_preflight_done = False
_preflight_sem = None


def _get_preflight_sem():
    global _preflight_sem
    if _preflight_sem is None:
        from gevent.lock import Semaphore

        _preflight_sem = Semaphore()
    return _preflight_sem


def _run_optional_preflight_once() -> None:
    """Runs Redis/Rust checks once per Locust process (first task), safe under concurrency."""
    global _preflight_done
    if _preflight_done:
        return
    with _get_preflight_sem():
        if _preflight_done:
            return
        no_optional = not (
            os.environ.get("LOADTEST_VERIFY_REDIS", "").strip().lower() in ("1", "true", "yes", "on")
            or os.environ.get("LOADTEST_VERIFY_RUST_ENGINE", "").strip().lower()
            in ("1", "true", "yes", "on")
        )
        if no_optional:
            _preflight_done = True
            return
        try:
            _verify_optional_infra_on_start()
        except Exception as e:
            log.error("optional preflight failed: %s", e)
            raise RuntimeError("LOADTEST optional dependency verification failed") from e
        _preflight_done = True


def _poll_clickhouse_for_trace(trace_id: str) -> bool:
    """Return True when a row exists for ``trace_id`` within ``_DEADLINE_S``."""
    client = _clickhouse_client()
    table = _validate_sql_identifier(os.environ.get("LOADTEST_CH_TABLE") or "fraud_decisions")
    sql = f"SELECT trace_id FROM {table} WHERE trace_id = {{tid:String}} LIMIT 1"
    deadline = time.monotonic() + _DEADLINE_S
    params = {"tid": trace_id}
    while time.monotonic() < deadline:
        result = client.query(sql, parameters=params)
        rows = result.result_rows
        if rows:
            return True
        gevent.sleep(_POLL_INTERVAL_S)
    return False


def _postgres_audit_row_exists(trace_id: str) -> bool:
    from sqlalchemy import text

    eng = _postgres_engine()
    tid = uuid.UUID(trace_id)
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM decision_audit WHERE trace_id = :tid LIMIT 1"),
            {"tid": tid},
        ).fetchone()
        return row is not None


class ProofPipelineUser(FastHttpUser):
    """Evaluate + ClickHouse proof (and optional Postgres audit row)."""

    host = os.environ.get("LOCUST_HOST") or os.environ.get("TARKA_LOADTEST_HOST") or ""
    wait_time = constant(0)

    def on_start(self) -> None:
        self.api_key = (os.environ.get("TARKA_LOADTEST_API_KEY") or os.environ.get("API_KEY") or "").strip()
        self.tenant_id = os.environ.get("LOADTEST_TENANT_ID", "loadtest").strip() or "loadtest"
        self.verify_pg = os.environ.get("LOADTEST_VERIFY_POSTGRES", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    @task(1)
    def evaluate_and_verify_proof(self) -> None:
        _run_optional_preflight_once()
        entity_id = f"load-{uuid.uuid4().hex[:12]}"
        payload = {
            "tenant_id": self.tenant_id,
            "event_type": "payment",
            "entity_id": entity_id,
            "payload": {"amount": 1.0},
            "metadata": {},
        }
        with self.client.post(
            "/v1/decisions/evaluate",
            json=payload,
            headers=self._headers(),
            name="/v1/decisions/evaluate",
            catch_response=True,
            timeout=60,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:500]}")
                return
            try:
                body = resp.json()
            except Exception as e:
                resp.failure(f"invalid JSON: {e}")
                return
            tid = body.get("trace_id")
            if not tid:
                resp.failure("missing trace_id in response body")
                return
            tid_str = str(tid)
            if not _trace_id_valid_otel_correlation(tid_str):
                resp.failure(f"trace_id failed validation: {tid_str!r}")
                return

            try:
                ch_ok = _poll_clickhouse_for_trace(tid_str)
            except Exception as e:
                resp.failure(f"ClickHouse verification error: {e}")
                return
            if not ch_ok:
                resp.failure(
                    f"No ClickHouse row for trace_id={tid_str} within {_DEADLINE_S}s "
                    f"(table={os.environ.get('LOADTEST_CH_TABLE') or 'fraud_decisions'})"
                )
                return

            if self.verify_pg:
                deadline = time.monotonic() + _DEADLINE_S
                ok_pg = False
                while time.monotonic() < deadline:
                    try:
                        if _postgres_audit_row_exists(tid_str):
                            ok_pg = True
                            break
                    except Exception as e:
                        resp.failure(f"postgres audit probe error: {e}")
                        return
                    gevent.sleep(_POLL_INTERVAL_S)
                if not ok_pg:
                    resp.failure(f"No Postgres decision_audit row for trace_id={tid_str} within {_DEADLINE_S}s")
                    return

            resp.success()


class ProofPipelineShape(LoadTestShape):
    """Ramp toward heavy concurrency for ~1k RPS class workloads (tune ``users`` for your SUT)."""

    stages = [
        {"duration": 60, "users": 400, "spawn_rate": 40.0},
        {"duration": 240, "users": 1600, "spawn_rate": 80.0},
    ]

    def tick(self) -> tuple[int, float] | None:
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]
            run_time -= stage["duration"]
        return None


# Usage with load shape (from this directory)::
#
#   locust -f locustfile.py --class-picker ProofPipelineUser \
#     --shape-class locustfile.ProofPipelineShape --host http://127.0.0.1:8005
#
# Headless ~1000 RPS class (tune ``-u`` from measured latency)::
#
#   locust -f locustfile.py --headless --host http://127.0.0.1:8005 \
#     -u 1200 -r 150 --run-time 10m --processes 4
